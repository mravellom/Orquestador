"""Tests for ApproverAgent: order evaluation logic."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.approver import ApproverAgent


@pytest.fixture
def approver():
    with patch("app.agents.approver.async_session"), \
         patch("app.agents.approver.settings") as mock_settings:
        mock_settings.acciones_auto_approve_enabled = False
        mock_settings.acciones_max_order_size_pct = 10.0
        mock_settings.acciones_auto_approve_max_usd = 100.0
        mock_settings.acciones_api_key = "test"
        mock_settings.redis_url = "redis://localhost"
        agent = ApproverAgent()
        agent.publish = AsyncMock()
        agent._settings = mock_settings
        yield agent, mock_settings


class TestEvaluateOrder:
    def test_approve_small_confident_order(self, approver):
        agent, settings = approver
        order = {"estimated_cost": 50, "signal_confidence": 0.8}
        result = agent._evaluate_order(order, total_capital=10000, drawdown_pct=5)
        assert result == "approve"

    def test_reject_high_drawdown(self, approver):
        agent, settings = approver
        order = {"estimated_cost": 50, "signal_confidence": 0.8}
        result = agent._evaluate_order(order, total_capital=10000, drawdown_pct=13)
        assert result == "reject"

    def test_reject_order_too_large(self, approver):
        agent, settings = approver
        order = {"estimated_cost": 1500, "signal_confidence": 0.8}
        result = agent._evaluate_order(order, total_capital=10000, drawdown_pct=5)
        assert result == "reject"

    def test_escalate_above_max_usd(self, approver):
        agent, settings = approver
        order = {"estimated_cost": 150, "signal_confidence": 0.8}
        result = agent._evaluate_order(order, total_capital=10000, drawdown_pct=5)
        assert result == "escalate"

    def test_escalate_low_confidence(self, approver):
        agent, settings = approver
        order = {"estimated_cost": 50, "signal_confidence": 0.4}
        result = agent._evaluate_order(order, total_capital=10000, drawdown_pct=5)
        assert result == "escalate"

    def test_reject_drawdown_takes_priority(self, approver):
        """Drawdown reject overrides all other checks."""
        agent, settings = approver
        order = {"estimated_cost": 10, "signal_confidence": 0.99}
        result = agent._evaluate_order(order, total_capital=10000, drawdown_pct=15)
        assert result == "reject"

    def test_zero_capital_doesnt_crash(self, approver):
        """With zero capital, pct check is skipped. Small confident order still approved."""
        agent, settings = approver
        order = {"estimated_cost": 50, "signal_confidence": 0.8}
        result = agent._evaluate_order(order, total_capital=0, drawdown_pct=5)
        assert result == "approve"


class TestRejectionReason:
    def test_drawdown_reason(self, approver):
        agent, _ = approver
        order = {"estimated_cost": 50}
        reason = agent._rejection_reason(order, total_capital=10000, drawdown_pct=15)
        assert "drawdown" in reason

    def test_size_reason(self, approver):
        agent, _ = approver
        order = {"estimated_cost": 2000}
        reason = agent._rejection_reason(order, total_capital=10000, drawdown_pct=5)
        assert "order size" in reason

    def test_multiple_reasons(self, approver):
        agent, _ = approver
        order = {"estimated_cost": 2000}
        reason = agent._rejection_reason(order, total_capital=10000, drawdown_pct=15)
        assert "drawdown" in reason
        assert "order size" in reason
