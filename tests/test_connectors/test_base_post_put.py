"""Tests for BaseConnector _safe_post and _safe_put methods."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.connectors.base import BaseConnector, HealthResult


class ConcreteConnector(BaseConnector):
    async def check_health(self):
        return HealthResult(is_healthy=True)
    async def collect_metrics(self):
        pass
    async def execute_action(self, action, params=None):
        pass


class TestSafePost:
    @pytest.mark.asyncio
    async def test_success_returns_response(self):
        c = ConcreteConnector("http://localhost")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch.object(c, "_post", new_callable=AsyncMock, return_value=mock_resp):
            resp, elapsed = await c._safe_post("/test", json={"key": "val"})
        assert resp is not None
        assert resp.status_code == 200
        assert elapsed >= 0
        assert c._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_failure_returns_none(self):
        c = ConcreteConnector("http://localhost")
        with patch.object(c, "_post", new_callable=AsyncMock, side_effect=httpx.ConnectError("fail")):
            resp, elapsed = await c._safe_post("/test")
        assert resp is None
        assert c._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_records_success_resets_failures(self):
        c = ConcreteConnector("http://localhost")
        c._consecutive_failures = 3
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch.object(c, "_post", new_callable=AsyncMock, return_value=mock_resp):
            await c._safe_post("/test")
        assert c._consecutive_failures == 0


class TestSafePut:
    @pytest.mark.asyncio
    async def test_success_returns_response(self):
        c = ConcreteConnector("http://localhost")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch.object(c, "_put", new_callable=AsyncMock, return_value=mock_resp):
            resp, elapsed = await c._safe_put("/test", json={"key": "val"})
        assert resp is not None
        assert resp.status_code == 200
        assert elapsed >= 0

    @pytest.mark.asyncio
    async def test_failure_returns_none(self):
        c = ConcreteConnector("http://localhost")
        with patch.object(c, "_put", new_callable=AsyncMock, side_effect=httpx.ConnectError("fail")):
            resp, elapsed = await c._safe_put("/test")
        assert resp is None
        assert c._consecutive_failures == 1


class TestPostDoesNotRetry4xx:
    @pytest.mark.asyncio
    async def test_4xx_returned_not_retried(self):
        c = ConcreteConnector("http://localhost")
        mock_resp = MagicMock()
        mock_resp.status_code = 400

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            resp = await c._post("/test", json={})
        assert resp.status_code == 400
        mock_client.post.assert_called_once()  # Only 1 call, no retry
