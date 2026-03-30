"""Shared test fixtures for the orchestrator test suite."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.engine.rules import ProjectMetrics


@pytest.fixture
def base_metrics():
    """Default ProjectMetrics with safe defaults."""
    return ProjectMetrics(
        slug="test_project",
        business_model="trading",
        handles_real_money=False,
    )


@pytest.fixture
def acciones_metrics():
    """ProjectMetrics configured like Acciones."""
    return ProjectMetrics(
        slug="acciones",
        business_model="trading",
        handles_real_money=True,
        eval_window_hours=168,
    )


@pytest.fixture
def libro_metrics():
    """ProjectMetrics configured like Libro."""
    return ProjectMetrics(
        slug="libro",
        business_model="publishing",
        handles_real_money=False,
        eval_window_hours=2160,
    )


@pytest.fixture
def casas_metrics():
    """ProjectMetrics configured like Casas."""
    return ProjectMetrics(
        slug="casas",
        business_model="marketplace",
        handles_real_money=False,
        eval_window_hours=336,
    )


@pytest.fixture
def mock_project():
    """Mock Project ORM model."""
    project = MagicMock()
    project.id = 1
    project.slug = "acciones"
    project.name = "Acciones Crypto Trading"
    project.business_model = "trading"
    project.status = "ACTIVE"
    project.handles_real_money = True
    project.requires_graceful_shutdown = True
    project.docker_compose_path = "/workspace/Acciones/backend"
    project.docker_project_name = "acciones-backend"
    project.monthly_budget_usd = 100
    project.eval_window_hours = 168
    project.eval_cadence_minutes = 5
    return project


@pytest.fixture
def mock_session():
    """Mock async database session."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.refresh = AsyncMock()
    return session
