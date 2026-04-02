"""Tests for new AccionesConnector actions: positions, risk config, strategies, orders."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.connectors.acciones import AccionesConnector


@pytest.fixture
def connector():
    return AccionesConnector("http://localhost:8001", api_key="test-key")


def mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = str(json_data)
    return resp


class TestListPositions:
    @pytest.mark.asyncio
    async def test_success(self, connector):
        positions = [{"id": 1, "symbol": "BTCUSDT"}, {"id": 2, "symbol": "AAPL"}]
        resp = mock_response(200, positions)
        with patch.object(connector, "_safe_get", new_callable=AsyncMock, return_value=(resp, 10)):
            result = await connector.execute_action("list_positions")
        assert result.success is True
        assert len(result.details["positions"]) == 2

    @pytest.mark.asyncio
    async def test_failure(self, connector):
        with patch.object(connector, "_safe_get", new_callable=AsyncMock, return_value=(None, 10)):
            result = await connector.execute_action("list_positions")
        assert result.success is False


class TestClosePosition:
    @pytest.mark.asyncio
    async def test_success(self, connector):
        resp = mock_response(200)
        with patch.object(connector, "_safe_post", new_callable=AsyncMock, return_value=(resp, 10)):
            result = await connector.execute_action("close_position", {"position_id": 42})
        assert result.success is True
        assert result.details["position_id"] == 42

    @pytest.mark.asyncio
    async def test_missing_position_id(self, connector):
        result = await connector.execute_action("close_position", {})
        assert result.success is False
        assert "position_id required" in result.message

    @pytest.mark.asyncio
    async def test_request_fails(self, connector):
        with patch.object(connector, "_safe_post", new_callable=AsyncMock, return_value=(None, 10)):
            result = await connector.execute_action("close_position", {"position_id": 1})
        assert result.success is False


class TestUpdateRiskConfig:
    @pytest.mark.asyncio
    async def test_success(self, connector):
        resp = mock_response(200)
        with patch.object(connector, "_safe_put", new_callable=AsyncMock, return_value=(resp, 10)):
            result = await connector.execute_action(
                "update_risk_config", {"config": {"max_positions": 3}}
            )
        assert result.success is True
        assert result.details["config_sent"] == {"max_positions": 3}

    @pytest.mark.asyncio
    async def test_failure(self, connector):
        with patch.object(connector, "_safe_put", new_callable=AsyncMock, return_value=(None, 10)):
            result = await connector.execute_action("update_risk_config", {"config": {}})
        assert result.success is False


class TestListStrategies:
    @pytest.mark.asyncio
    async def test_success(self, connector):
        strategies = [{"id": 1, "name": "Momentum"}, {"id": 2, "name": "ML"}]
        resp = mock_response(200, strategies)
        with patch.object(connector, "_safe_get", new_callable=AsyncMock, return_value=(resp, 10)):
            result = await connector.execute_action("list_strategies")
        assert result.success is True
        assert len(result.details["strategies"]) == 2


class TestActivateDeactivateStrategy:
    @pytest.mark.asyncio
    async def test_activate_success(self, connector):
        resp = mock_response(200)
        with patch.object(connector, "_safe_post", new_callable=AsyncMock, return_value=(resp, 10)):
            result = await connector.execute_action("activate_strategy", {"strategy_id": 1})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_activate_missing_id(self, connector):
        result = await connector.execute_action("activate_strategy", {})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_deactivate_success(self, connector):
        resp = mock_response(200)
        with patch.object(connector, "_safe_post", new_callable=AsyncMock, return_value=(resp, 10)):
            result = await connector.execute_action("deactivate_strategy", {"strategy_id": 2})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_deactivate_missing_id(self, connector):
        result = await connector.execute_action("deactivate_strategy", {})
        assert result.success is False


class TestApproveRejectOrder:
    @pytest.mark.asyncio
    async def test_approve_success(self, connector):
        resp = mock_response(200)
        with patch.object(connector, "_safe_post", new_callable=AsyncMock, return_value=(resp, 10)):
            result = await connector.execute_action("approve_order", {"order_id": 10})
        assert result.success is True
        assert result.details["order_id"] == 10

    @pytest.mark.asyncio
    async def test_approve_missing_id(self, connector):
        result = await connector.execute_action("approve_order", {})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_reject_success(self, connector):
        resp = mock_response(200)
        with patch.object(connector, "_safe_post", new_callable=AsyncMock, return_value=(resp, 10)):
            result = await connector.execute_action(
                "reject_order", {"order_id": 10, "reason": "Too risky"}
            )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_reject_missing_id(self, connector):
        result = await connector.execute_action("reject_order", {})
        assert result.success is False


class TestHealthWithReconciliation:
    @pytest.mark.asyncio
    async def test_reconciliation_ok(self, connector):
        health_resp = mock_response(200, {
            "status": "healthy",
            "checks": {"database": {"status": "healthy"}, "redis": {"status": "healthy"}},
        })
        recon_resp = mock_response(200, {"issues": []})

        async def side_effect(path):
            if "reconciliation" in path:
                return recon_resp, 10
            return health_resp, 10

        with patch.object(connector, "_safe_get", new_callable=AsyncMock, side_effect=side_effect):
            result = await connector.check_health()

        assert result.is_healthy is True
        assert result.reconciliation_ok is True

    @pytest.mark.asyncio
    async def test_reconciliation_issues(self, connector):
        health_resp = mock_response(200, {
            "status": "healthy",
            "checks": {"database": {"status": "healthy"}, "redis": {"status": "healthy"}},
        })
        recon_resp = mock_response(200, {"issues": [{"type": "orphan_order"}]})

        async def side_effect(path):
            if "reconciliation" in path:
                return recon_resp, 10
            return health_resp, 10

        with patch.object(connector, "_safe_get", new_callable=AsyncMock, side_effect=side_effect):
            result = await connector.check_health()

        assert result.is_healthy is True
        assert result.reconciliation_ok is False

    @pytest.mark.asyncio
    async def test_reconciliation_unavailable(self, connector):
        health_resp = mock_response(200, {
            "status": "healthy",
            "checks": {"database": {"status": "healthy"}, "redis": {"status": "healthy"}},
        })

        async def side_effect(path):
            if "reconciliation" in path:
                return None, 10
            return health_resp, 10

        with patch.object(connector, "_safe_get", new_callable=AsyncMock, side_effect=side_effect):
            result = await connector.check_health()

        assert result.is_healthy is True
        assert result.reconciliation_ok is None
