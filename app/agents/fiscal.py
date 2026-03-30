"""Fiscal Agent: collects financial and operational metrics from MVPs."""
import structlog
from sqlalchemy import select

from app.agents.base import BaseAgent
from app.config import settings, PROJECT_REGISTRY
from app.connectors.acciones import AccionesConnector
from app.connectors.compraventa import CompraVentaConnector
from app.connectors.libro import LibroConnector
from app.connectors.ideas import IdeasConnector
from app.connectors.casas import CasasConnector
from app.database import async_session
from app.models.metric_snapshot import MetricSnapshot
from app.models.project import Project

logger = structlog.get_logger()

CONNECTOR_MAP = {
    "acciones": AccionesConnector,
    "compraventa": CompraVentaConnector,
    "libro": LibroConnector,
    "ideas": IdeasConnector,
    "casas": CasasConnector,
}


class FiscalAgent(BaseAgent):
    name = "fiscal"
    cadence_seconds = 60  # Base cadence; actual per-project cadence managed internally
    publish_channel = "orq:metrics"

    def __init__(self):
        super().__init__()
        self._connectors: dict = {}
        self._last_collection: dict[str, int] = {}  # slug -> cycle_count at last collection

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

    def _should_collect(self, slug: str) -> bool:
        """Check if enough cycles have passed for this project's cadence."""
        for cfg in PROJECT_REGISTRY:
            if cfg.slug == slug:
                cycles_needed = max(1, (cfg.eval_cadence_minutes * 60) // self.cadence_seconds)
                last = self._last_collection.get(slug, 0)
                return (self._cycle_count - last) >= cycles_needed
        return False

    async def run_cycle(self):
        async with async_session() as session:
            result = await session.execute(
                select(Project).where(Project.status == "ACTIVE")
            )
            projects = result.scalars().all()

        for project in projects:
            if not self._should_collect(project.slug):
                continue

            connector = self._get_connector(project.slug)
            if not connector:
                continue

            try:
                metrics = await connector.collect_metrics()
                self._last_collection[project.slug] = self._cycle_count

                # Persist
                async with async_session() as session:
                    snapshot = MetricSnapshot(
                        project_id=project.id,
                        metric_type=metrics.metric_type,
                        pnl_usd=metrics.pnl_usd,
                        roi_pct=metrics.roi_pct,
                        total_capital=metrics.total_capital,
                        available_capital=metrics.available_capital,
                        win_rate_pct=metrics.win_rate_pct,
                        drawdown_pct=metrics.drawdown_pct,
                        sharpe_ratio=metrics.sharpe_ratio,
                        revenue_usd=metrics.revenue_usd,
                        active_users=metrics.active_users,
                        items_processed=metrics.items_processed,
                        false_positive_rate=metrics.false_positive_rate,
                        raw_data=metrics.raw_data,
                    )
                    session.add(snapshot)
                    await session.commit()

                await self.publish("metrics_collected", {
                    "project_slug": project.slug,
                    "metric_type": metrics.metric_type,
                    "pnl_usd": metrics.pnl_usd,
                    "roi_pct": metrics.roi_pct,
                    "revenue_usd": metrics.revenue_usd,
                    "items_processed": metrics.items_processed,
                })

                logger.info("Metrics collected", project=project.slug)

            except Exception as e:
                logger.error("Failed to collect metrics", project=project.slug, error=str(e))
