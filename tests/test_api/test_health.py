"""Tests for /health endpoint."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture
def client():
    """Create test client with mocked lifespan (no real DB/Redis/agents)."""
    from contextlib import asynccontextmanager
    from fastapi.testclient import TestClient

    @asynccontextmanager
    async def mock_lifespan(app):
        yield

    from app.main import app
    app.router.lifespan_context = mock_lifespan
    return TestClient(app)


class TestHealthEndpoint:
    @patch("app.main.engine")
    @patch("app.main.aioredis")
    def test_health_returns_status(self, mock_redis_mod, mock_engine, client):
        # Mock DB
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        ))

        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        mock_redis.close = AsyncMock()
        mock_redis_mod.from_url = MagicMock(return_value=mock_redis)

        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "checks" in data
        assert "database" in data["checks"]
        assert "redis" in data["checks"]
