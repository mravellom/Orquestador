"""Tests for MonitorAgent."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.connectors.base import HealthResult


@pytest.fixture
def monitor():
    with patch("app.agents.monitor.async_session"), \
         patch("app.agents.monitor.settings"):
        from app.agents.monitor import MonitorAgent
        agent = MonitorAgent()
        agent.publish = AsyncMock()
        return agent


@pytest.fixture
def healthy_result():
    return HealthResult(is_healthy=True, http_status=200, response_ms=30)


@pytest.fixture
def unhealthy_result():
    return HealthResult(is_healthy=False, http_status=500, response_ms=100, error_message="Server error")


@pytest.fixture
def mock_active_project():
    p = MagicMock()
    p.id = 1
    p.slug = "acciones"
    p.name = "Acciones"
    p.status = "ACTIVE"
    return p


class TestMonitorRunCycle:
    @pytest.mark.asyncio
    async def test_healthy_check_persists(self, monitor, healthy_result, mock_active_project):
        mock_connector = AsyncMock()
        mock_connector.check_health = AsyncMock(return_value=healthy_result)
        monitor._get_connector = MagicMock(return_value=mock_connector)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        # Mock both session calls: one for projects, one for health check persist
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_active_project]

        with patch("app.agents.monitor.async_session", return_value=mock_session):
            mock_session.execute = AsyncMock(return_value=mock_result)
            await monitor.run_cycle()

        assert monitor._failure_counts.get("acciones", 0) == 0

    @pytest.mark.asyncio
    async def test_unhealthy_increments_failure(self, monitor, unhealthy_result, mock_active_project):
        mock_connector = AsyncMock()
        mock_connector.check_health = AsyncMock(return_value=unhealthy_result)
        monitor._get_connector = MagicMock(return_value=mock_connector)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_active_project]

        with patch("app.agents.monitor.async_session", return_value=mock_session):
            mock_session.execute = AsyncMock(return_value=mock_result)
            await monitor.run_cycle()

        assert monitor._failure_counts["acciones"] == 1

    @pytest.mark.asyncio
    async def test_three_failures_triggers_alert(self, monitor, unhealthy_result, mock_active_project):
        mock_connector = AsyncMock()
        mock_connector.check_health = AsyncMock(return_value=unhealthy_result)
        monitor._get_connector = MagicMock(return_value=mock_connector)
        monitor._failure_counts["acciones"] = 2  # Already had 2 failures

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_active_project]

        with patch("app.agents.monitor.async_session", return_value=mock_session):
            mock_session.execute = AsyncMock(return_value=mock_result)
            await monitor.run_cycle()

        assert monitor._failure_counts["acciones"] == 3
        # Check alert was published
        alert_calls = [c for c in monitor.publish.call_args_list if c[0][0] == "alert"]
        assert len(alert_calls) == 1

    @pytest.mark.asyncio
    async def test_four_failures_no_duplicate_alert(self, monitor, unhealthy_result, mock_active_project):
        mock_connector = AsyncMock()
        mock_connector.check_health = AsyncMock(return_value=unhealthy_result)
        monitor._get_connector = MagicMock(return_value=mock_connector)
        monitor._failure_counts["acciones"] = 3  # Already at 3

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_active_project]

        with patch("app.agents.monitor.async_session", return_value=mock_session):
            mock_session.execute = AsyncMock(return_value=mock_result)
            await monitor.run_cycle()

        # No alert at count=4 (only at exactly 3)
        alert_calls = [c for c in monitor.publish.call_args_list if c[0][0] == "alert"]
        assert len(alert_calls) == 0

    @pytest.mark.asyncio
    async def test_recovery_after_failures(self, monitor, healthy_result, mock_active_project):
        mock_connector = AsyncMock()
        mock_connector.check_health = AsyncMock(return_value=healthy_result)
        monitor._get_connector = MagicMock(return_value=mock_connector)
        monitor._failure_counts["acciones"] = 3  # Was failing

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_active_project]

        with patch("app.agents.monitor.async_session", return_value=mock_session):
            mock_session.execute = AsyncMock(return_value=mock_result)
            await monitor.run_cycle()

        assert monitor._failure_counts["acciones"] == 0
        recovery_calls = [c for c in monitor.publish.call_args_list if c[0][0] == "recovery"]
        assert len(recovery_calls) == 1

    @pytest.mark.asyncio
    async def test_no_recovery_if_never_failed(self, monitor, healthy_result, mock_active_project):
        mock_connector = AsyncMock()
        mock_connector.check_health = AsyncMock(return_value=healthy_result)
        monitor._get_connector = MagicMock(return_value=mock_connector)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_active_project]

        with patch("app.agents.monitor.async_session", return_value=mock_session):
            mock_session.execute = AsyncMock(return_value=mock_result)
            await monitor.run_cycle()

        recovery_calls = [c for c in monitor.publish.call_args_list if c[0][0] == "recovery"]
        assert len(recovery_calls) == 0

    @pytest.mark.asyncio
    async def test_no_connector_skips_project(self, monitor, mock_active_project):
        monitor._get_connector = MagicMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_active_project]

        with patch("app.agents.monitor.async_session", return_value=mock_session):
            mock_session.execute = AsyncMock(return_value=mock_result)
            await monitor.run_cycle()

        # No publish calls since connector was None
        assert monitor.publish.call_count == 0

    @pytest.mark.asyncio
    async def test_no_active_projects(self, monitor):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        with patch("app.agents.monitor.async_session", return_value=mock_session):
            mock_session.execute = AsyncMock(return_value=mock_result)
            await monitor.run_cycle()

        assert monitor.publish.call_count == 0
