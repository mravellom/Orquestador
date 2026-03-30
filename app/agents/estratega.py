"""Estratega Agent: central brain that evaluates rules and proposes decisions."""
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select, func

from app.agents.base import BaseAgent
from app.config import settings, PROJECT_REGISTRY
from app.database import async_session
from app.engine.rules import ALL_RULES, ProjectMetrics, Rule
from app.engine.scoring import calculate_portfolio_score
from app.models.decision import Decision
from app.models.health_check import HealthCheck
from app.models.metric_snapshot import MetricSnapshot
from app.models.project import Project

logger = structlog.get_logger()


class EstrategaAgent(BaseAgent):
    name = "estratega"
    cadence_seconds = settings.estratega_cadence_minutes * 60
    publish_channel = "orq:decisions"

    def __init__(self):
        super().__init__()
        self._last_rule_fire: dict[str, datetime] = {}  # "rule_id:slug" -> last fire time

    def _is_on_cooldown(self, rule: Rule, slug: str) -> bool:
        key = f"{rule.id}:{slug}"
        last = self._last_rule_fire.get(key)
        if last and (datetime.utcnow() - last).total_seconds() < rule.cooldown_hours * 3600:
            return True
        return False

    async def _build_metrics(self, project: Project) -> ProjectMetrics:
        """Aggregate latest metrics into a ProjectMetrics object for rule evaluation."""
        cfg = next((c for c in PROJECT_REGISTRY if c.slug == project.slug), None)

        metrics = ProjectMetrics(
            slug=project.slug,
            business_model=project.business_model,
            handles_real_money=project.handles_real_money,
            eval_window_hours=cfg.eval_window_hours if cfg else 720,
            monthly_budget=float(project.monthly_budget_usd or 0),
        )

        async with async_session() as session:
            # Health: count consecutive unhealthy checks
            health_q = (
                select(HealthCheck)
                .where(HealthCheck.project_id == project.id)
                .order_by(HealthCheck.checked_at.desc())
                .limit(100)
            )
            checks = (await session.execute(health_q)).scalars().all()

            if checks:
                metrics.is_healthy = checks[0].is_healthy
                unhealthy_streak = 0
                for c in checks:
                    if not c.is_healthy:
                        unhealthy_streak += 1
                    else:
                        break
                if unhealthy_streak > 0 and checks:
                    first_unhealthy = checks[min(unhealthy_streak - 1, len(checks) - 1)]
                    metrics.unhealthy_hours = (datetime.utcnow() - first_unhealthy.checked_at.replace(tzinfo=None)).total_seconds() / 3600

            # Latest metric snapshot
            snap_q = (
                select(MetricSnapshot)
                .where(MetricSnapshot.project_id == project.id)
                .order_by(MetricSnapshot.captured_at.desc())
                .limit(1)
            )
            latest = (await session.execute(snap_q)).scalar_one_or_none()

            if latest:
                metrics.roi_pct = float(latest.roi_pct) if latest.roi_pct is not None else None
                metrics.pnl_usd = float(latest.pnl_usd) if latest.pnl_usd is not None else None
                metrics.drawdown_pct = float(latest.drawdown_pct) if latest.drawdown_pct is not None else None
                metrics.win_rate_pct = float(latest.win_rate_pct) if latest.win_rate_pct is not None else None
                metrics.sharpe_ratio = float(latest.sharpe_ratio) if latest.sharpe_ratio is not None else None
                metrics.revenue_usd = float(latest.revenue_usd) if latest.revenue_usd is not None else None
                metrics.active_users = latest.active_users
                metrics.items_processed = latest.items_processed
                metrics.false_positive_rate = float(latest.false_positive_rate) if latest.false_positive_rate is not None else None

                # Check raw_data for extras
                raw = latest.raw_data or {}
                risk_data = raw.get("risk", {})
                if isinstance(risk_data, dict):
                    metrics.circuit_breaker_active = risk_data.get("circuit_breaker_active", False)
                    compliance = raw.get("risk", {})
                    if isinstance(compliance, dict) and "risk_level" in compliance:
                        metrics.compliance_risk = compliance["risk_level"]

            # ROI trend: simple slope from last N snapshots
            window_start = datetime.utcnow() - timedelta(hours=metrics.eval_window_hours)
            trend_q = (
                select(MetricSnapshot)
                .where(
                    MetricSnapshot.project_id == project.id,
                    MetricSnapshot.captured_at >= window_start,
                    MetricSnapshot.roi_pct.isnot(None),
                )
                .order_by(MetricSnapshot.captured_at.asc())
            )
            snapshots = (await session.execute(trend_q)).scalars().all()
            if len(snapshots) >= 2:
                first_roi = float(snapshots[0].roi_pct)
                last_roi = float(snapshots[-1].roi_pct)
                days = max(1, (snapshots[-1].captured_at - snapshots[0].captured_at).total_seconds() / 86400)
                metrics.roi_trend = (last_roi - first_roi) / days

        return metrics

    async def run_cycle(self):
        async with async_session() as session:
            result = await session.execute(
                select(Project).where(Project.status == "ACTIVE")
            )
            projects = result.scalars().all()

        for project in projects:
            metrics = await self._build_metrics(project)

            # Calculate portfolio score
            score = calculate_portfolio_score(
                is_healthy=metrics.is_healthy,
                roi_pct=metrics.roi_pct,
                roi_trend=metrics.roi_trend,
                win_rate_pct=metrics.win_rate_pct,
                drawdown_pct=metrics.drawdown_pct,
                revenue_usd=metrics.revenue_usd,
                items_processed=metrics.items_processed,
                false_positive_rate=metrics.false_positive_rate,
            )

            logger.info("Portfolio score", project=project.slug, score=score)

            # Evaluate rules
            for rule in ALL_RULES:
                if "*" not in rule.applies_to and project.slug not in rule.applies_to:
                    continue

                if self._is_on_cooldown(rule, project.slug):
                    continue

                result = rule.evaluate(metrics)
                if not result.fired:
                    continue

                # Check if human approval is needed
                needs_human = result.requires_human
                if result.decision_type == "KILL" and project.handles_real_money:
                    needs_human = True
                if settings.kill_requires_human_approval and result.decision_type == "KILL":
                    needs_human = True

                # Create decision
                async with async_session() as session:
                    decision = Decision(
                        project_id=project.id,
                        decision_type=result.decision_type,
                        status="PROPOSED",
                        confidence=result.confidence,
                        reasons=[result.reason],
                        rule_triggers=[rule.id],
                        requires_human_approval=needs_human,
                    )
                    session.add(decision)
                    await session.commit()
                    decision_id = decision.id

                self._last_rule_fire[f"{rule.id}:{project.slug}"] = datetime.utcnow()

                await self.publish("decision_proposed", {
                    "decision_id": decision_id,
                    "project_slug": project.slug,
                    "decision_type": result.decision_type,
                    "confidence": result.confidence,
                    "reason": result.reason,
                    "requires_human": needs_human,
                })

                logger.warning(
                    "Decision proposed",
                    project=project.slug,
                    type=result.decision_type,
                    confidence=result.confidence,
                    rule=rule.id,
                )
