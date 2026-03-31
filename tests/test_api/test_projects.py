"""Tests for /api/v1/projects endpoints."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient


@pytest.fixture
def client(mock_session, mock_project):
    @asynccontextmanager
    async def mock_lifespan(app):
        yield

    from app.main import app
    from app.database import get_session
    app.router.lifespan_context = mock_lifespan

    async def _override():
        yield mock_session

    app.dependency_overrides[get_session] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestListProjects:
    def test_returns_projects(self, client, mock_session, mock_project):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_project]
        mock_session.execute.return_value = mock_result

        resp = client.get("/api/v1/projects")
        assert resp.status_code == 200

    def test_empty_list(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        resp = client.get("/api/v1/projects")
        assert resp.status_code == 200


class TestGetProject:
    def test_found(self, client, mock_session, mock_project):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute.return_value = mock_result

        resp = client.get("/api/v1/projects/acciones")
        assert resp.status_code == 200

    def test_not_found(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        resp = client.get("/api/v1/projects/nonexistent")
        assert resp.status_code == 404


class TestPauseResume:
    def test_pause(self, client, mock_session, mock_project):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute.return_value = mock_result

        resp = client.post("/api/v1/projects/acciones/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "PAUSED"

    def test_resume(self, client, mock_session, mock_project):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute.return_value = mock_result

        resp = client.post("/api/v1/projects/acciones/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACTIVE"

    def test_pause_not_found(self, client, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        resp = client.post("/api/v1/projects/nonexistent/pause")
        assert resp.status_code == 404
