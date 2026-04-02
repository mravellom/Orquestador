"""Tests for AccionesWebSocketManager: message handling and status."""
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock

from app.connectors.acciones_ws import AccionesWebSocketManager, REDIS_CHANNEL_MAP


@pytest.fixture
def ws_manager():
    with patch("app.connectors.acciones_ws.settings") as mock_settings:
        mock_settings.acciones_ws_url = "ws://localhost:8001/ws"
        mock_settings.acciones_api_key = "test-key"
        mock_settings.redis_url = "redis://localhost"
        mock_settings.acciones_ws_enabled = True
        mgr = AccionesWebSocketManager(
            ws_url="ws://localhost:8001/ws",
            api_key="test-key",
            redis_url="redis://localhost",
        )
        yield mgr


class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_risk_message_published_to_redis(self, ws_manager):
        mock_redis = AsyncMock()
        ws_manager._redis = mock_redis

        msg = json.dumps({"channel": "risk", "data": {"drawdown_pct": 12.5}})
        await ws_manager._handle_message(msg)

        mock_redis.publish.assert_called()
        call_args = mock_redis.publish.call_args_list
        channels = [c[0][0] for c in call_args]
        assert "orq:ws:risk" in channels

    @pytest.mark.asyncio
    async def test_system_message_published(self, ws_manager):
        mock_redis = AsyncMock()
        ws_manager._redis = mock_redis

        msg = json.dumps({"channel": "system", "data": {"status": "RUNNING"}})
        await ws_manager._handle_message(msg)

        channels = [c[0][0] for c in mock_redis.publish.call_args_list]
        assert "orq:ws:system" in channels

    @pytest.mark.asyncio
    async def test_unknown_channel_ignored(self, ws_manager):
        mock_redis = AsyncMock()
        ws_manager._redis = mock_redis

        msg = json.dumps({"channel": "unknown_channel", "data": {}})
        await ws_manager._handle_message(msg)

        mock_redis.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_json_ignored(self, ws_manager):
        mock_redis = AsyncMock()
        ws_manager._redis = mock_redis

        await ws_manager._handle_message("not valid json {{{")
        mock_redis.publish.assert_not_called()


class TestRiskFastPath:
    @pytest.mark.asyncio
    async def test_circuit_breaker_alert_published(self, ws_manager):
        mock_redis = AsyncMock()
        ws_manager._redis = mock_redis

        msg = json.dumps({
            "channel": "risk",
            "data": {"circuit_breaker_active": True, "drawdown_pct": 15},
        })
        await ws_manager._handle_message(msg)

        # Should publish to both orq:ws:risk AND orq:health
        channels = [c[0][0] for c in mock_redis.publish.call_args_list]
        assert "orq:ws:risk" in channels
        assert "orq:health" in channels

    @pytest.mark.asyncio
    async def test_no_alert_when_cb_inactive(self, ws_manager):
        mock_redis = AsyncMock()
        ws_manager._redis = mock_redis

        msg = json.dumps({
            "channel": "risk",
            "data": {"circuit_breaker_active": False},
        })
        await ws_manager._handle_message(msg)

        channels = [c[0][0] for c in mock_redis.publish.call_args_list]
        assert "orq:ws:risk" in channels
        assert "orq:health" not in channels


class TestSystemFastPath:
    @pytest.mark.asyncio
    async def test_halt_publishes_to_health(self, ws_manager):
        mock_redis = AsyncMock()
        ws_manager._redis = mock_redis

        msg = json.dumps({
            "channel": "system",
            "data": {"status": "HALTED"},
        })
        await ws_manager._handle_message(msg)

        channels = [c[0][0] for c in mock_redis.publish.call_args_list]
        assert "orq:health" in channels

    @pytest.mark.asyncio
    async def test_running_no_health_alert(self, ws_manager):
        mock_redis = AsyncMock()
        ws_manager._redis = mock_redis

        msg = json.dumps({
            "channel": "system",
            "data": {"status": "RUNNING"},
        })
        await ws_manager._handle_message(msg)

        channels = [c[0][0] for c in mock_redis.publish.call_args_list]
        assert "orq:health" not in channels


class TestGetStatus:
    def test_returns_status_dict(self, ws_manager):
        status = ws_manager.get_status()
        assert status["name"] == "acciones_ws"
        assert status["running"] is False
        assert status["consecutive_failures"] == 0

    def test_tracks_failures(self, ws_manager):
        ws_manager._consecutive_failures = 5
        status = ws_manager.get_status()
        assert status["consecutive_failures"] == 5


class TestRedisChannelMap:
    def test_all_channels_mapped(self):
        assert "risk" in REDIS_CHANNEL_MAP
        assert "system" in REDIS_CHANNEL_MAP
        assert "positions" in REDIS_CHANNEL_MAP
        assert "portfolio" in REDIS_CHANNEL_MAP
        assert len(REDIS_CHANNEL_MAP) == 4
