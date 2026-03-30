"""Reporter Agent: generates and sends portfolio reports daily."""
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select

from app.agents.base import BaseAgent
from app.config import settings
from app.database import async_session
from app.engine.scoring import calculate_portfolio_score
from app.models.alert import Alert
from app.models.decision import Decision
from app.models.health_check import HealthCheck
from app.models.metric_snapshot import MetricSnapshot
from app.models.project import Project
from app.notifications.telegram import TelegramNotifier

logger = structlog.get_logger()


class ReporterAgent(BaseAgent):
    name = "reporter"
    cadence_seconds = 3600  # Check every hour, send at scheduled times
    publish_channel = "orq:alerts"

    def __init__(self):
        super().__init__()
        self.telegram = TelegramNotifier()
        self._last_report_hour: int | None = None

    def _should_send_report(self) -> bool:
        """Check if current hour matches any scheduled report time."""
        now = datetime.utcnow()
        current_hour = now.hour

        if current_hour == self._last_report_hour:
            return False

        schedule = settings.reporter_schedule.split(",")
        for time_str in schedule:
            parts = time_str.strip().split(":")
            if len(parts) >= 1:
                scheduled_hour = int(parts[0])
                if current_hour == scheduled_hour:
                    return True
        return False

    async def run_cycle(self):
        if not self._should_send_report():
            return

        self._last_report_hour = datetime.utcnow().hour
        report = await self.generate_report()
        await self.telegram.send_report(report)
        logger.info("Portfolio report sent")

    async def generate_report(self, hours: int = 24) -> str:
        """Generate a portfolio report for the last N hours."""
        since = datetime.utcnow() - timedelta(hours=hours)

        async with async_session() as session:
            projects = (await session.execute(select(Project))).scalars().all()

            lines = [
                "📊 *PORTFOLIO REPORT*",
                f"Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
                "",
            ]

            active_count = sum(1 for p in projects if p.status == "ACTIVE")
            lines.append(f"*PORTFOLIO HEALTH:* {active_count}/{len(projects)} ACTIVE")
            lines.append("")

            for project in projects:
                # Latest health
                health = (await session.execute(
                    select(HealthCheck)
                    .where(HealthCheck.project_id == project.id)
                    .order_by(HealthCheck.checked_at.desc())
                    .limit(1)
                )).scalar_one_or_none()

                # Latest metrics
                metric = (await session.execute(
                    select(MetricSnapshot)
                    .where(MetricSnapshot.project_id == project.id)
                    .order_by(MetricSnapshot.captured_at.desc())
                    .limit(1)
                )).scalar_one_or_none()

                health_status = "✅" if (health and health.is_healthy) else "❌" if health else "❓"
                status_emoji = {"ACTIVE": "🟢", "PAUSED": "🟡", "KILLED": "🔴"}.get(project.status, "⚪")

                lines.append(f"--- *{project.name}* ---")
                lines.append(f"Status: {status_emoji} {project.status} | Health: {health_status}")

                if metric:
                    metric_parts = []
                    if metric.pnl_usd is not None:
                        sign = "+" if float(metric.pnl_usd) >= 0 else ""
                        metric_parts.append(f"PnL: {sign}{float(metric.pnl_usd):.2f} USD")
                    if metric.roi_pct is not None:
                        metric_parts.append(f"ROI: {float(metric.roi_pct):.1f}%")
                    if metric.win_rate_pct is not None:
                        metric_parts.append(f"Win Rate: {float(metric.win_rate_pct):.1f}%")
                    if metric.revenue_usd is not None:
                        metric_parts.append(f"Revenue: ${float(metric.revenue_usd):.2f}")
                    if metric.drawdown_pct is not None:
                        metric_parts.append(f"Drawdown: {float(metric.drawdown_pct):.1f}%")
                    if metric.items_processed is not None:
                        metric_parts.append(f"Items: {metric.items_processed}")
                    if metric.active_users is not None:
                        metric_parts.append(f"Users: {metric.active_users}")
                    if metric.false_positive_rate is not None:
                        metric_parts.append(f"FP Rate: {float(metric.false_positive_rate):.0f}%")

                    if metric_parts:
                        lines.append(" | ".join(metric_parts))

                    # Portfolio score
                    score = calculate_portfolio_score(
                        is_healthy=health.is_healthy if health else False,
                        roi_pct=float(metric.roi_pct) if metric.roi_pct else None,
                        roi_trend=None,
                        win_rate_pct=float(metric.win_rate_pct) if metric.win_rate_pct else None,
                        drawdown_pct=float(metric.drawdown_pct) if metric.drawdown_pct else None,
                        revenue_usd=float(metric.revenue_usd) if metric.revenue_usd else None,
                        items_processed=metric.items_processed,
                        false_positive_rate=float(metric.false_positive_rate) if metric.false_positive_rate else None,
                    )
                    signal = "SCALE" if score > 70 else "KILL?" if score < 30 else "HOLD"
                    lines.append(f"Score: {score}/100 | Signal: *{signal}*")
                else:
                    lines.append("No metrics available")

                lines.append("")

            # Recent decisions
            decisions = (await session.execute(
                select(Decision)
                .where(Decision.proposed_at >= since)
                .order_by(Decision.proposed_at.desc())
                .limit(10)
            )).scalars().all()

            if decisions:
                lines.append(f"*DECISIONS (last {hours}h):* {len(decisions)}")
                for d in decisions:
                    p = (await session.execute(select(Project).where(Project.id == d.project_id))).scalar_one_or_none()
                    pname = p.slug if p else "?"
                    lines.append(f"• {pname}: {d.decision_type} ({d.status})")
                lines.append("")

            # Recent alerts
            alerts = (await session.execute(
                select(Alert)
                .where(Alert.created_at >= since)
                .order_by(Alert.created_at.desc())
                .limit(10)
            )).scalars().all()

            if alerts:
                lines.append(f"*ALERTS (last {hours}h):* {len(alerts)}")
                for a in alerts:
                    lines.append(f"• [{a.severity}] {a.message[:80]}")

        return "\n".join(lines)
