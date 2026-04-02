"""Estratega Agent: central brain that evaluates rules and proposes decisions."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select, func

from app.agents.base import BaseAgent
from app.config import settings, PROJECT_REGISTRY
from app.database import async_session
from app.engine.rules import ALL_RULES, ProjectMetrics, Rule
from app.engine.scoring import calculate_portfolio_score, evaluate_signal_with_hysteresis
from app.models.decision import Decision
from app.models.health_check import HealthCheck
from app.models.metric_snapshot import MetricSnapshot
from app.models.project import Project

logger = structlog.get_logger()


class EstrategaAgent(BaseAgent):
    name = "estratega"
    cadence_seconds = settings.estratega_cadence_minutes * 60
    publish_channel = "orq:decisions"

    # Tactical rules: fast-response, evaluated every cycle (~10 min)
    TACTICAL_RULE_IDS = frozenset({
        "UNIV_HEALTH_DEAD",
        "ACC_CIRCUIT_BREAKER",
        "ACC_DAILY_LOSS",
        "FIN_DRAWDOWN",
        "UNIV_BUDGET_EXCEEDED",
        "ACC_RECONCILIATION",
        "ACC_STOCKS_MARKET_HOURS",
    })

    # Strategic rules: need time to be meaningful, evaluated every 6 hours
    STRATEGIC_CADENCE_HOURS = 6

    def __init__(self):
        super().__init__()
        self._last_rule_fire: dict[str, datetime] = {}  # "rule_id:slug" -> last fire time
        self._score_history: dict[str, list[float]] = {}  # slug -> last N scores
        self._current_signals: dict[str, str] = {}  # slug -> current signal (HOLD/SCALE/KILL)
        self._last_strategic_cycle: datetime | None = None

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
                metrics.total_capital = float(latest.total_capital) if latest.total_capital is not None else None
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

                # Reconciliation issues from health details stored in raw_data
                recon_data = raw.get("reconciliation", {})
                if isinstance(recon_data, dict):
                    issues = recon_data.get("issues", [])
                    metrics.reconciliation_issues = len(issues) if isinstance(issues, list) else 0

            # Previous snapshot: extract circuit_breaker_active for CB reset rule
            prev_snap_q = (
                select(MetricSnapshot)
                .where(MetricSnapshot.project_id == project.id)
                .order_by(MetricSnapshot.captured_at.desc())
                .offset(1)
                .limit(1)
            )
            previous = (await session.execute(prev_snap_q)).scalar_one_or_none()
            if previous:
                prev_raw = previous.raw_data or {}
                prev_risk = prev_raw.get("risk", {})
                if isinstance(prev_risk, dict):
                    metrics.circuit_breaker_active_previous = prev_risk.get("circuit_breaker_active", False)

            # --- Phase 2: enrich metrics from raw_data ---
            if latest:
                raw = latest.raw_data or {}

                # Asset class breakdown
                breakdown = raw.get("portfolio_breakdown", [])
                if isinstance(breakdown, list):
                    for entry in breakdown:
                        ac = entry.get("asset_class", "").upper()
                        if ac == "CRYPTO":
                            metrics.crypto_pnl_usd = entry.get("pnl") or entry.get("daily_pnl")
                            metrics.crypto_capital = entry.get("total_capital")
                        elif ac in ("STOCKS", "STOCK"):
                            metrics.stocks_pnl_usd = entry.get("pnl") or entry.get("daily_pnl")
                            metrics.stocks_capital = entry.get("total_capital")

                # Count stock positions open
                open_positions = raw.get("open_positions", [])
                if isinstance(open_positions, list):
                    metrics.stocks_positions_open = sum(
                        1 for p in open_positions
                        if isinstance(p, dict) and p.get("asset_class", "").upper() in ("STOCKS", "STOCK")
                    )

                # Stock market hours check (ET timezone)
                now_et = datetime.now(ZoneInfo("America/New_York"))
                weekday = now_et.weekday()  # 0=Monday, 6=Sunday
                hour_min = now_et.hour * 100 + now_et.minute
                metrics.is_stock_market_open = (
                    weekday < 5  # Mon-Fri
                    and 930 <= hour_min <= 1600
                )

                # Total capital for asset class checks
                if metrics.total_capital is None and (metrics.crypto_capital or metrics.stocks_capital):
                    metrics.total_capital = (metrics.crypto_capital or 0) + (metrics.stocks_capital or 0)

                # Strategy performance
                strategies = raw.get("strategies", [])
                per_strat = raw.get("per_strategy_analytics", [])
                if isinstance(strategies, list) and isinstance(per_strat, list):
                    # Merge strategy info with analytics
                    analytics_by_id = {}
                    for a in per_strat:
                        sid = a.get("strategy_id") or a.get("id")
                        if sid:
                            analytics_by_id[sid] = a

                    for s in strategies:
                        sid = s.get("id")
                        a = analytics_by_id.get(sid, {})
                        metrics.strategy_performance.append({
                            "id": sid,
                            "name": s.get("name", ""),
                            "is_active": s.get("is_active", True),
                            "asset_class": s.get("asset_class", ""),
                            "win_rate_pct": a.get("win_rate") or a.get("win_rate_pct", 50),
                            "trades_count": a.get("total_trades") or a.get("trades_count", 0),
                            "pnl_usd": a.get("total_pnl") or a.get("pnl_usd", 0),
                            "sharpe_ratio": a.get("sharpe_ratio"),
                        })

                    metrics.active_strategy_count = sum(1 for s in strategies if s.get("is_active", True))

                # ML shadow performance
                ml_shadow = raw.get("ml_shadow", {})
                if isinstance(ml_shadow, dict):
                    metrics.ml_shadow_win_rate = ml_shadow.get("win_rate") or ml_shadow.get("ml_win_rate")
                    metrics.live_win_rate = ml_shadow.get("live_win_rate") or (
                        float(metrics.win_rate_pct) if metrics.win_rate_pct is not None else None
                    )

                # Paper vs live
                pvl = raw.get("paper_vs_live", {})
                if isinstance(pvl, dict):
                    metrics.paper_pnl = pvl.get("paper_pnl") or pvl.get("paper", {}).get("pnl")
                    metrics.live_pnl = pvl.get("live_pnl") or pvl.get("live", {}).get("pnl")

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

        # Determine whether strategic rules should run this cycle
        now = datetime.utcnow()
        run_strategic = (
            self._last_strategic_cycle is None
            or (now - self._last_strategic_cycle).total_seconds()
            >= self.STRATEGIC_CADENCE_HOURS * 3600
        )
        if run_strategic:
            logger.info("Strategic evaluation due — running full rule set")

        for project in projects:
            metrics = await self._build_metrics(project)

            # Determine enrichment params for scoring
            asset_class_count = 1
            if metrics.crypto_capital and metrics.stocks_capital:
                asset_class_count = 2

            pending_count = 0
            async with async_session() as session:
                snap_q = (
                    select(MetricSnapshot)
                    .where(MetricSnapshot.project_id == project.id)
                    .order_by(MetricSnapshot.captured_at.desc())
                    .limit(1)
                )
                latest_snap = (await session.execute(snap_q)).scalar_one_or_none()
                if latest_snap and latest_snap.raw_data:
                    pending = latest_snap.raw_data.get("pending_approvals", [])
                    pending_count = len(pending) if isinstance(pending, list) else 0

            reconciliation_ok = metrics.reconciliation_issues == 0

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
                reconciliation_ok=reconciliation_ok,
                asset_class_count=asset_class_count,
                strategy_diversity=metrics.active_strategy_count or None,
                pending_approvals_count=pending_count,
            )

            # Track score history and apply hysteresis
            if project.slug not in self._score_history:
                self._score_history[project.slug] = []
            self._score_history[project.slug].append(score)
            # Keep last 10 scores
            self._score_history[project.slug] = self._score_history[project.slug][-10:]

            current_signal = self._current_signals.get(project.slug, "HOLD")
            signal = evaluate_signal_with_hysteresis(
                score, self._score_history[project.slug], current_signal,
            )
            self._current_signals[project.slug] = signal

            # Inject portfolio score into metrics for score-based rules
            metrics.portfolio_score = score

            logger.info("Portfolio score", project=project.slug, score=score, signal=signal)

            # Evaluate rules
            for rule in ALL_RULES:
                # Tier filter: always run tactical; only run strategic when due
                is_tactical = rule.id in self.TACTICAL_RULE_IDS
                if not is_tactical and not run_strategic:
                    continue

                if "*" not in rule.applies_to and project.slug not in rule.applies_to:
                    continue

                if self._is_on_cooldown(rule, project.slug):
                    continue

                result = rule.evaluate(metrics)
                if not result.fired:
                    continue

                # Hysteresis guard: suppress SCALE if signal is not SCALE, suppress KILL if signal is not KILL
                # ADJUST_RISK and RESUME bypass hysteresis — they are reactive corrections
                if result.decision_type == "SCALE" and signal != "SCALE":
                    continue
                if result.decision_type == "KILL" and signal != "KILL" and rule.id != "UNIV_HEALTH_DEAD":
                    continue

                # Check if human approval is needed
                needs_human = result.requires_human
                if result.decision_type == "KILL" and project.handles_real_money:
                    needs_human = True
                if settings.kill_requires_human_approval and result.decision_type == "KILL":
                    needs_human = True

                # Build action_params for strategy-level decisions
                action_params = {}
                if result.decision_type in ("DEACTIVATE_STRATEGY", "ACTIVATE_STRATEGY"):
                    # Extract strategy info from the reason (the rule includes it)
                    for strat in metrics.strategy_performance:
                        name = strat.get("name", "")
                        if name and name in result.reason:
                            action_params["strategy_id"] = strat.get("id")
                            action_params["strategy_name"] = name
                            break

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
                        action_params=action_params,
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

        # Mark strategic cycle as complete so next one fires after STRATEGIC_CADENCE_HOURS
        if run_strategic:
            self._last_strategic_cycle = datetime.utcnow()
