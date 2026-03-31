"""Monitor Agent: checks health of all active MVP projects every 30s."""
import structlog
from sqlalchemy import select

from app.agents.base import BaseAgent
from app.config import settings, PROJECT_REGISTRY
from app.notifications.telegram import TelegramNotifier
from app.connectors.acciones import AccionesConnector
from app.connectors.compraventa import CompraVentaConnector
from app.connectors.libro import LibroConnector
from app.connectors.ideas import IdeasConnector
from app.connectors.casas import CasasConnector
from app.database import async_session
from app.models.health_check import HealthCheck
from app.models.project import Project

logger = structlog.get_logger()

CONNECTOR_MAP = {
    "acciones": AccionesConnector,
    "compraventa": CompraVentaConnector,
    "libro": LibroConnector,
    "ideas": IdeasConnector,
    "casas": CasasConnector,
}


class MonitorAgent(BaseAgent):
    name = "monitor"
    cadence_seconds = settings.monitor_cadence_seconds
    publish_channel = "orq:health"

    def __init__(self):
        super().__init__()
        self._connectors: dict = {}
        self._failure_counts: dict[str, int] = {}
        self._notifier: TelegramNotifier | None = None

    def _get_notifier(self):
        if self._notifier is None:
            self._notifier = TelegramNotifier()
        return self._notifier

    def _get_connector(self, slug: str):
        if slug not in self._connectors:
            for cfg in PROJECT_REGISTRY:
                if cfg.slug == slug:
                    cls = CONNECTOR_MAP.get(slug)
                    if cls:
                        api_key = getattr(settings, cfg.api_key_env, "") if cfg.api_key_env else None
                        self._connectors[slug] = cls(
                            base_url=cfg.base_url,
                            api_key=api_key or None,
                        )
                    break
        return self._connectors.get(slug)

    async def run_cycle(self):
        async with async_session() as session:
            result = await session.execute(
                select(Project).where(Project.status == "ACTIVE")
            )
            projects = result.scalars().all()

        for project in projects:
            connector = self._get_connector(project.slug)
            if not connector:
                continue

            health = await connector.check_health()

            # Track consecutive failures
            if not health.is_healthy:
                self._failure_counts[project.slug] = self._failure_counts.get(project.slug, 0) + 1
            else:
                prev_failures = self._failure_counts.get(project.slug, 0)
                self._failure_counts[project.slug] = 0
                if prev_failures >= 3:
                    await self.publish("recovery", {
                        "project_slug": project.slug,
                        "previous_failures": prev_failures,
                    })

            # Persist health check
            async with async_session() as session:
                check = HealthCheck(
                    project_id=project.id,
                    is_healthy=health.is_healthy,
                    http_status=health.http_status,
                    response_ms=health.response_ms,
                    database_ok=health.database_ok,
                    redis_ok=health.redis_ok,
                    details=health.details,
                    error_message=health.error_message,
                )
                session.add(check)
                await session.commit()

            # Publish to Redis
            await self.publish("health_check", {
                "project_slug": project.slug,
                "is_healthy": health.is_healthy,
                "response_ms": health.response_ms,
                "consecutive_failures": self._failure_counts.get(project.slug, 0),
            })

            # Alert on 3 consecutive failures
            if self._failure_counts.get(project.slug, 0) == 3:
                await self.publish("alert", {
                    "project_slug": project.slug,
                    "severity": "CRITICAL",
                    "message": f"{project.name} has been unhealthy for 3 consecutive checks",
                })
                logger.warning("Project unhealthy", project=project.slug, failures=3)
                await self._get_notifier().send_alert(
                    severity="CRITICAL",
                    project=project.name,
                    message=f"Unhealthy for 3 consecutive checks ({3 * self.cadence_seconds}s)",
                )
