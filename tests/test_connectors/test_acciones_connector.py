"""Tests for AccionesConnector: health, metrics, actions."""
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


class TestCheckHealth:
    @pytest.mark.asyncio
    async def test_unreachable_returns_unhealthy(self, connector):
        with patch.object(connector, "_safe_get", new_callable=AsyncMock, return_value=(None, 100)):
            result = await connector.check_health()
        assert result.is_healthy is False
        assert result.error_message == "Unreachable"
        assert result.response_ms == 100

    @pytest.mark.asyncio
    async def test_non_200_returns_unhealthy(self, connector):
        resp = mock_response(500)
        with patch.object(connector, "_safe_get", new_callable=AsyncMock, return_value=(resp, 50)):
            result = await connector.check_health()
        assert result.is_healthy is False
        assert result.http_status == 500

    @pytest.mark.asyncio
    async def test_200_healthy(self, connector):
        resp = mock_response(200, {
            "status": "healthy",
            "checks": {
                "database": {"status": "healthy"},
                "redis": {"status": "healthy"},
            },
        })
        with patch.object(connector, "_safe_get", new_callable=AsyncMock, return_value=(resp, 30)):
            result = await connector.check_health()
        assert result.is_healthy is True
        assert result.database_ok is True
        assert result.redis_ok is True

    @pytest.mark.asyncio
    async def test_200_degraded(self, connector):
        resp = mock_response(200, {"status": "degraded", "checks": {}})
        with patch.object(connector, "_safe_get", new_callable=AsyncMock, return_value=(resp, 30)):
            result = await connector.check_health()
        assert result.is_healthy is False

    @pytest.mark.asyncio
    async def test_missing_checks_defaults_false(self, connector):
        resp = mock_response(200, {"status": "healthy"})
        with patch.object(connector, "_safe_get", new_callable=AsyncMock, return_value=(resp, 30)):
            result = await connector.check_health()
        assert result.is_healthy is True
        assert result.database_ok is False
        assert result.redis_ok is False


class TestCollectMetrics:
    @pytest.mark.asyncio
    async def test_all_endpoints_200(self, connector):
        portfolio_resp = mock_response(200, {"total_capital": 10000, "available_capital": 8000, "pnl": 42.5})
        analytics_resp = mock_response(200, {"win_rate": 58.2, "sharpe_ratio": 1.3})
        risk_resp = mock_response(200, {"drawdown_pct": 3.2})

        call_count = 0
        async def side_effect(path):
            nonlocal call_count
            call_count += 1
            if "portfolio" in path:
                return portfolio_resp, 10
            elif "analytics" in path:
                return analytics_resp, 10
            elif "risk" in path:
                return risk_resp, 10
            return None, 10

        with patch.object(connector, "_safe_get", new_callable=AsyncMock, side_effect=side_effect):
            result = await connector.collect_metrics()

        assert result.total_capital == 10000
        assert result.available_capital == 8000
        assert result.pnl_usd == 42.5
        assert result.win_rate_pct == 58.2
        assert result.sharpe_ratio == 1.3
        assert result.drawdown_pct == 3.2

    @pytest.mark.asyncio
    async def test_portfolio_fails_others_ok(self, connector):
        analytics_resp = mock_response(200, {"win_rate": 58.2, "sharpe_ratio": 1.3})
        risk_resp = mock_response(200, {"drawdown_pct": 3.2})

        async def side_effect(path):
            if "portfolio" in path:
                return None, 10
            elif "analytics" in path:
                return analytics_resp, 10
            elif "risk" in path:
                return risk_resp, 10
            return None, 10

        with patch.object(connector, "_safe_get", new_callable=AsyncMock, side_effect=side_effect):
            result = await connector.collect_metrics()

        assert result.total_capital is None
        assert result.pnl_usd is None
        assert result.win_rate_pct == 58.2

    @pytest.mark.asyncio
    async def test_all_fail_returns_empty(self, connector):
        with patch.object(connector, "_safe_get", new_callable=AsyncMock, return_value=(None, 10)):
            result = await connector.collect_metrics()

        assert result.total_capital is None
        assert result.pnl_usd is None
        assert result.win_rate_pct is None
        assert result.metric_type == "financial"


class TestExecuteAction:
    @pytest.mark.asyncio
    async def test_halt_success(self, connector):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "halted"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await connector.execute_action("halt")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_check_positions_returns_count(self, connector):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"open_positions": 3}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await connector.execute_action("check_positions")
        assert result.success is True
        assert result.details["open_positions"] == 3

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, connector):
        result = await connector.execute_action("foo")
        assert result.success is False
        assert "Unknown action" in result.message
