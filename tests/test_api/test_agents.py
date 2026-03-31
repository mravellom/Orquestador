"""Tests for /api/v1/agents endpoints."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    @asynccontextmanager
    async def mock_lifespan(app):
        yield

    from app.main import app
    app.router.lifespan_context = mock_lifespan

    # Register a fake agent
    from app.api.agents import _agents
    mock_agent = MagicMock()
    mock_agent.name = "test_agent"
    mock_agent.get_status.return_value = {"name": "test_agent", "running": True, "cycles": 5}
    mock_agent.run_cycle = AsyncMock()
    _agents["test_agent"] = mock_agent

    yield TestClient(app)
    _agents.clear()


class TestAgentsStatus:
    def test_returns_status(self, client):
        resp = client.get("/api/v1/agents/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "test_agent" in data
        assert data["test_agent"]["running"] is True


class TestTriggerAgent:
    def test_trigger_existing(self, client):
        resp = client.post("/api/v1/agents/test_agent/trigger")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cycle_triggered"

    def test_trigger_nonexistent(self, client):
        resp = client.post("/api/v1/agents/nonexistent/trigger")
        assert resp.status_code == 200
        assert "error" in resp.json()
