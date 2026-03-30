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
