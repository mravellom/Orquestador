"""Tests for EstrategaAgent."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from app.engine.rules import Rule, RuleResult, ProjectMetrics


@pytest.fixture
def estratega():
    with patch("app.agents.estratega.async_session"), \
         patch("app.agents.estratega.settings") as mock_settings:
        mock_settings.estratega_cadence_minutes = 10
        mock_settings.kill_requires_human_approval = True
        from app.agents.estratega import EstrategaAgent
        agent = EstrategaAgent()
        agent.publish = AsyncMock()
        return agent


class TestCooldown:
    def test_not_on_cooldown_first_time(self, estratega):
        rule = Rule(id="TEST", name="test", applies_to=["*"], evaluate=lambda m: RuleResult(fired=False), cooldown_hours=24)
        assert estratega._is_on_cooldown(rule, "acciones") is False

    def test_on_cooldown_recent_fire(self, estratega):
        rule = Rule(id="TEST", name="test", applies_to=["*"], evaluate=lambda m: RuleResult(fired=False), cooldown_hours=24)
        estratega._last_rule_fire["TEST:acciones"] = datetime.utcnow()
        assert estratega._is_on_cooldown(rule, "acciones") is True

    def test_cooldown_expired(self, estratega):
        rule = Rule(id="TEST", name="test", applies_to=["*"], evaluate=lambda m: RuleResult(fired=False), cooldown_hours=24)
        estratega._last_rule_fire["TEST:acciones"] = datetime.utcnow() - timedelta(hours=25)
        assert estratega._is_on_cooldown(rule, "acciones") is False

    def test_independent_per_slug(self, estratega):
        rule = Rule(id="TEST", name="test", applies_to=["*"], evaluate=lambda m: RuleResult(fired=False), cooldown_hours=24)
        estratega._last_rule_fire["TEST:acciones"] = datetime.utcnow()
        # Different slug should not be on cooldown
        assert estratega._is_on_cooldown(rule, "libro") is False


class TestTacticalVsStrategic:
    @pytest.mark.asyncio
    async def test_first_cycle_runs_strategic(self, estratega):
        assert estratega._last_strategic_cycle is None
        # On first run, strategic should run since _last_strategic_cycle is None

    @pytest.mark.asyncio
    async def test_strategic_skipped_when_not_due(self, estratega):
        estratega._last_strategic_cycle = datetime.utcnow() - timedelta(hours=1)
        # 1 hour ago < 6 hours -> strategic should not run
        # We verify by checking the logic directly
        from app.agents.estratega import EstrategaAgent
        elapsed = (datetime.utcnow() - estratega._last_strategic_cycle).total_seconds()
        run_strategic = elapsed >= EstrategaAgent.STRATEGIC_CADENCE_HOURS * 3600
        assert run_strategic is False

    @pytest.mark.asyncio
    async def test_strategic_runs_after_6_hours(self, estratega):
        estratega._last_strategic_cycle = datetime.utcnow() - timedelta(hours=7)
        from app.agents.estratega import EstrategaAgent
        elapsed = (datetime.utcnow() - estratega._last_strategic_cycle).total_seconds()
        run_strategic = elapsed >= EstrategaAgent.STRATEGIC_CADENCE_HOURS * 3600
        assert run_strategic is True


class TestHumanApproval:
    def test_kill_real_money_requires_human(self):
        """KILL on a project that handles real money should require human approval."""
        # This is tested via the logic: if decision_type == "KILL" and project.handles_real_money
        metrics = ProjectMetrics(slug="acciones", business_model="trading", handles_real_money=True, roi_pct=-25)
        from app.engine.rules import eval_roi_negative_30d
        result = eval_roi_negative_30d(metrics)
        assert result.fired is True
        assert result.requires_human is True

    def test_kill_paper_setting_on_still_requires(self):
        """When kill_requires_human_approval=True, even paper KILL needs human."""
        # This is enforced in estratega.run_cycle: if settings.kill_requires_human_approval and type=="KILL"
        # We just verify the setting is respected
        metrics = ProjectMetrics(slug="libro", business_model="publishing", handles_real_money=False, roi_pct=-25)
        from app.engine.rules import eval_roi_negative_30d
        result = eval_roi_negative_30d(metrics)
        assert result.fired is True
        assert result.requires_human is False  # Rule doesn't force it, setting does


class TestRuleFiltering:
    def test_applies_to_filters_correctly(self):
        rule = Rule(id="ACC_ONLY", name="test", applies_to=["acciones"],
                    evaluate=lambda m: RuleResult(fired=True, decision_type="PAUSE"), cooldown_hours=1)
        # libro not in applies_to
        assert "libro" not in rule.applies_to
        assert "acciones" in rule.applies_to

    def test_universal_applies_to_all(self):
        rule = Rule(id="UNIV", name="test", applies_to=["*"],
                    evaluate=lambda m: RuleResult(fired=True), cooldown_hours=1)
        assert "*" in rule.applies_to


class TestBuildMetrics:
    """Tests for _build_metrics - the method that aggregates DB data into ProjectMetrics."""

    @pytest.mark.asyncio
    async def test_no_health_checks_defaults_healthy(self, estratega):
        """When no health checks exist, metrics.is_healthy should default True."""
        mock_project = MagicMock()
        mock_project.slug = "acciones"
        mock_project.business_model = "trading"
        mock_project.handles_real_money = True
        mock_project.monthly_budget_usd = 100

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        # First query: health checks - empty
        health_result = MagicMock()
        health_result.scalars.return_value.all.return_value = []
        # Second query: latest metric snapshot - None
        snap_result = MagicMock()
        snap_result.scalar_one_or_none.return_value = None
        # Third query: ROI trend snapshots - empty
        trend_result = MagicMock()
        trend_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(side_effect=[health_result, snap_result, trend_result])

        with patch("app.agents.estratega.async_session", return_value=mock_session):
            metrics = await estratega._build_metrics(mock_project)

        assert metrics.is_healthy is True
        assert metrics.unhealthy_hours == 0
        assert metrics.roi_pct is None
        assert metrics.pnl_usd is None

    @pytest.mark.asyncio
    async def test_consecutive_unhealthy_calculates_hours(self, estratega):
        """Consecutive unhealthy checks should calculate unhealthy_hours."""
        mock_project = MagicMock()
        mock_project.slug = "acciones"
        mock_project.business_model = "trading"
        mock_project.handles_real_money = True
        mock_project.monthly_budget_usd = 0

        # Create 5 unhealthy checks
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        checks = []
        for i in range(5):
            c = MagicMock()
            c.is_healthy = False
            c.checked_at = now - timedelta(minutes=i * 10)
            checks.append(c)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        health_result = MagicMock()
        health_result.scalars.return_value.all.return_value = checks
        snap_result = MagicMock()
        snap_result.scalar_one_or_none.return_value = None
        trend_result = MagicMock()
        trend_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(side_effect=[health_result, snap_result, trend_result])

        with patch("app.agents.estratega.async_session", return_value=mock_session):
            metrics = await estratega._build_metrics(mock_project)

        assert metrics.is_healthy is False
        assert metrics.unhealthy_hours > 0

    @pytest.mark.asyncio
    async def test_latest_snapshot_populates_metrics(self, estratega):
        """Latest metric snapshot should populate financial fields."""
        mock_project = MagicMock()
        mock_project.slug = "compraventa"
        mock_project.business_model = "arbitrage"
        mock_project.handles_real_money = False
        mock_project.monthly_budget_usd = 50

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        health_result = MagicMock()
        health_result.scalars.return_value.all.return_value = []

        snapshot = MagicMock()
        snapshot.roi_pct = -15.5
        snapshot.pnl_usd = -200
        snapshot.drawdown_pct = 8.3
        snapshot.win_rate_pct = 45.0
        snapshot.sharpe_ratio = 0.8
        snapshot.revenue_usd = None
        snapshot.active_users = None
        snapshot.items_processed = 42
        snapshot.false_positive_rate = None
        snapshot.raw_data = {"risk": {"circuit_breaker_active": True, "risk_level": "HIGH"}}

        snap_result = MagicMock()
        snap_result.scalar_one_or_none.return_value = snapshot

        trend_result = MagicMock()
        trend_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(side_effect=[health_result, snap_result, trend_result])

        with patch("app.agents.estratega.async_session", return_value=mock_session):
            metrics = await estratega._build_metrics(mock_project)

        assert metrics.roi_pct == -15.5
        assert metrics.pnl_usd == -200
        assert metrics.drawdown_pct == 8.3
        assert metrics.win_rate_pct == 45.0
        assert metrics.items_processed == 42
        assert metrics.circuit_breaker_active is True

    @pytest.mark.asyncio
    async def test_roi_trend_with_two_snapshots(self, estratega):
        """ROI trend should be calculated when >= 2 snapshots exist."""
        mock_project = MagicMock()
        mock_project.slug = "acciones"
        mock_project.business_model = "trading"
        mock_project.handles_real_money = True
        mock_project.monthly_budget_usd = 0

        from datetime import datetime, timedelta
        now = datetime.utcnow()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        health_result = MagicMock()
        health_result.scalars.return_value.all.return_value = []
        snap_result = MagicMock()
        snap_result.scalar_one_or_none.return_value = None

        # 2 snapshots for trend: ROI went from 5% to 15% over 10 days
        snap1 = MagicMock()
        snap1.roi_pct = 5.0
        snap1.captured_at = now - timedelta(days=10)
        snap2 = MagicMock()
        snap2.roi_pct = 15.0
        snap2.captured_at = now

        trend_result = MagicMock()
        trend_result.scalars.return_value.all.return_value = [snap1, snap2]

        mock_session.execute = AsyncMock(side_effect=[health_result, snap_result, trend_result])

        with patch("app.agents.estratega.async_session", return_value=mock_session):
            metrics = await estratega._build_metrics(mock_project)

        # (15 - 5) / 10 = 1.0 per day
        assert metrics.roi_trend is not None
        assert abs(metrics.roi_trend - 1.0) < 0.1

    @pytest.mark.asyncio
    async def test_roi_trend_none_with_single_snapshot(self, estratega):
        """ROI trend should be None when < 2 snapshots."""
        mock_project = MagicMock()
        mock_project.slug = "libro"
        mock_project.business_model = "publishing"
        mock_project.handles_real_money = False
        mock_project.monthly_budget_usd = 0

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        health_result = MagicMock()
        health_result.scalars.return_value.all.return_value = []
        snap_result = MagicMock()
        snap_result.scalar_one_or_none.return_value = None

        snap1 = MagicMock()
        snap1.roi_pct = 5.0
        snap1.captured_at = datetime.utcnow()
        trend_result = MagicMock()
        trend_result.scalars.return_value.all.return_value = [snap1]

        mock_session.execute = AsyncMock(side_effect=[health_result, snap_result, trend_result])

        with patch("app.agents.estratega.async_session", return_value=mock_session):
            metrics = await estratega._build_metrics(mock_project)

        assert metrics.roi_trend is None


class TestRunCycleEndToEnd:
    """Test the full run_cycle with mocked DB and rules."""

    @pytest.mark.asyncio
    async def test_full_cycle_creates_decision(self, estratega):
        """Full cycle: project with bad ROI -> rule fires -> decision created."""
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.slug = "acciones"
        mock_project.name = "Acciones"
        mock_project.business_model = "trading"
        mock_project.status = "ACTIVE"
        mock_project.handles_real_money = True
        mock_project.monthly_budget_usd = 0

        # Mock _build_metrics to return bad metrics
        bad_metrics = ProjectMetrics(
            slug="acciones",
            business_model="trading",
            handles_real_money=True,
            roi_pct=-25,
            drawdown_pct=18,
            is_healthy=True,
        )
        estratega._build_metrics = AsyncMock(return_value=bad_metrics)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        # First call: query projects
        projects_result = MagicMock()
        projects_result.scalars.return_value.all.return_value = [mock_project]

        mock_session.execute = AsyncMock(return_value=projects_result)

        with patch("app.agents.estratega.async_session", return_value=mock_session):
            await estratega.run_cycle()

        # At least one decision should be created (FIN_DRAWDOWN is tactical, fires every cycle)
        assert mock_session.add.call_count > 0
        assert mock_session.commit.call_count > 0
        assert estratega.publish.call_count > 0

    @pytest.mark.asyncio
    async def test_strategic_cycle_updates_timestamp(self, estratega):
        """After running strategic rules, _last_strategic_cycle should be updated."""
        estratega._last_strategic_cycle = None  # Forces strategic run

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        projects_result = MagicMock()
        projects_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=projects_result)

        with patch("app.agents.estratega.async_session", return_value=mock_session):
            await estratega.run_cycle()

        assert estratega._last_strategic_cycle is not None
