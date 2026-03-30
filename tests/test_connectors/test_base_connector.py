"""Tests for BaseConnector: circuit breaker, retry, headers."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

import httpx

from app.connectors.base import BaseConnector, HealthResult


class ConcreteConnector(BaseConnector):
    """Concrete implementation for testing."""
    async def check_health(self):
        return HealthResult(is_healthy=True)

    async def collect_metrics(self):
        pass

    async def execute_action(self, action, params=None):
        pass


class TestHeaders:
    def test_with_api_key(self):
        c = ConcreteConnector("http://localhost", api_key="abc123")
        headers = c._headers()
        assert headers["X-API-Key"] == "abc123"
        assert headers["Accept"] == "application/json"

    def test_without_api_key(self):
        c = ConcreteConnector("http://localhost")
        headers = c._headers()
        assert "X-API-Key" not in headers
        assert headers["Accept"] == "application/json"


class TestCircuitBreaker:
    def test_opens_after_5_failures(self):
        c = ConcreteConnector("http://localhost")
        for _ in range(5):
            c._record_failure()
        assert c._consecutive_failures == 5
        assert c._circuit_open_until is not None

    def test_resets_on_success(self):
        c = ConcreteConnector("http://localhost")
        for _ in range(3):
            c._record_failure()
        c._record_success()
        assert c._consecutive_failures == 0
        assert c._circuit_open_until is None

    def test_circuit_open_blocks(self):
        c = ConcreteConnector("http://localhost")
        c._circuit_open_until = datetime.utcnow() + timedelta(seconds=60)
        assert c._is_circuit_open() is True

    def test_circuit_closes_after_timeout(self):
        c = ConcreteConnector("http://localhost")
        c._circuit_open_until = datetime.utcnow() - timedelta(seconds=1)
        assert c._is_circuit_open() is False
        assert c._circuit_open_until is None

    def test_circuit_closed_by_default(self):
        c = ConcreteConnector("http://localhost")
        assert c._is_circuit_open() is False


class TestSafeGet:
    @pytest.mark.asyncio
    async def test_success_returns_response(self):
        c = ConcreteConnector("http://localhost")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch.object(c, "_get", new_callable=AsyncMock, return_value=mock_resp):
            resp, elapsed = await c._safe_get("/test")
        assert resp is not None
        assert resp.status_code == 200
        assert elapsed >= 0
        assert c._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_failure_returns_none(self):
        c = ConcreteConnector("http://localhost")
        with patch.object(c, "_get", new_callable=AsyncMock, side_effect=httpx.ConnectError("fail")):
            resp, elapsed = await c._safe_get("/test")
        assert resp is None
        assert elapsed >= 0
        assert c._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_timing_measured_on_failure(self):
        c = ConcreteConnector("http://localhost")
        with patch.object(c, "_get", new_callable=AsyncMock, side_effect=Exception("boom")):
            resp, elapsed = await c._safe_get("/test")
        assert resp is None
        assert isinstance(elapsed, int)
