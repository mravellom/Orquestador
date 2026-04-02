"""Fiscal Agent: collects financial and operational metrics from MVPs."""
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
from app.models.metric_snapshot import MetricSnapshot
from app.models.strategy_snapshot import StrategySnapshot
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
                        crypto_pnl_usd=metrics.crypto_pnl_usd,
                        stocks_pnl_usd=metrics.stocks_pnl_usd,
                        raw_data=metrics.raw_data,
                    )
                    session.add(snapshot)
                    await session.commit()

                # Persist per-strategy snapshots (Acciones only)
                await self._persist_strategy_snapshots(project.id, metrics.raw_data)

                await self.publish("metrics_collected", {
                    "project_slug": project.slug,
                    "metric_type": metrics.metric_type,
                    "pnl_usd": metrics.pnl_usd,
                    "roi_pct": metrics.roi_pct,
                    "revenue_usd": metrics.revenue_usd,
                    "items_processed": metrics.items_processed,
                })

                logger.info("Metrics collected", project=project.slug)

                # Alert on critical financial thresholds
                if metrics.drawdown_pct and metrics.drawdown_pct > 15:
                    await self._get_notifier().send_alert(
                        severity="WARNING",
                        project=project.name,
                        message=f"Drawdown at {metrics.drawdown_pct:.1f}% (threshold: 15%)",
                    )
                if metrics.roi_pct is not None and metrics.roi_pct < -20:
                    await self._get_notifier().send_alert(
                        severity="CRITICAL",
                        project=project.name,
                        message=f"ROI at {metrics.roi_pct:.1f}% (threshold: -20%)",
                    )

            except Exception as e:
                logger.error("Failed to collect metrics", project=project.slug, error=str(e))

    async def _persist_strategy_snapshots(self, project_id: int, raw_data: dict):
        """Save a StrategySnapshot row for each strategy found in raw_data."""
        strategies = raw_data.get("strategies", [])
        per_strat = raw_data.get("per_strategy_analytics", [])

        if not isinstance(strategies, list) or not strategies:
            return

        # Build analytics lookup by strategy id
        analytics_by_id: dict[int, dict] = {}
        if isinstance(per_strat, list):
            for a in per_strat:
                sid = a.get("strategy_id") or a.get("id")
                if sid is not None:
                    analytics_by_id[sid] = a

        async with async_session() as session:
            for s in strategies:
                sid = s.get("id")
                if sid is None:
                    continue

                a = analytics_by_id.get(sid, {})
                snap = StrategySnapshot(
                    project_id=project_id,
                    strategy_id=sid,
                    strategy_name=s.get("name", ""),
                    is_active=s.get("is_active", True),
                    asset_class=s.get("asset_class"),
                    win_rate_pct=a.get("win_rate") or a.get("win_rate_pct"),
                    pnl_usd=a.get("total_pnl") or a.get("pnl_usd"),
                    trades_count=a.get("total_trades") or a.get("trades_count"),
                    sharpe_ratio=a.get("sharpe_ratio"),
                )
                session.add(snap)

            await session.commit()

        logger.info("Strategy snapshots saved", project_id=project_id, count=len(strategies))
