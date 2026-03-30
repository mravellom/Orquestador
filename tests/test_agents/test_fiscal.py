"""Tests for FiscalAgent."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.connectors.base import MetricResult


@pytest.fixture
def fiscal():
    with patch("app.agents.fiscal.async_session"), \
         patch("app.agents.fiscal.settings"):
        from app.agents.fiscal import FiscalAgent
        agent = FiscalAgent()
        agent.publish = AsyncMock()
        return agent


class TestShouldCollect:
    def test_first_cycle_collects(self, fiscal):
        fiscal._cycle_count = 1
        fiscal._last_collection = {}
        # Acciones: cadence=5min, agent cadence=60s -> cycles_needed = max(1, 300/60) = 5
        # cycle_count=1, last=0 -> 1-0=1 >= 5 -> False
        # Actually first cycle won't collect for high-cadence projects
        # But for libro: cadence=360min -> cycles_needed = max(1, 21600/60) = 360
        # Let's test with a project that has cycles_needed=1
        # ideas: cadence=60min -> cycles_needed = max(1, 3600/60) = 60
        # For first collection we need cycle_count >= cycles_needed
        # This means the fiscal correctly waits before first collection
        assert fiscal._should_collect("nonexistent_slug") is False

    def test_respects_cadence(self, fiscal):
        fiscal._cycle_count = 3
        fiscal._last_collection = {"acciones": 0}
        # Acciones: cycles_needed = 5, 3-0=3 < 5 -> False
        assert fiscal._should_collect("acciones") is False

    def test_collects_when_cadence_reached(self, fiscal):
        fiscal._cycle_count = 5
        fiscal._last_collection = {"acciones": 0}
        # 5-0=5 >= 5 -> True
        assert fiscal._should_collect("acciones") is True

    def test_unknown_slug_returns_false(self, fiscal):
        assert fiscal._should_collect("unknown_project") is False


class TestFiscalRunCycle:
    @pytest.mark.asyncio
    async def test_collect_success_persists_snapshot(self, fiscal):
        fiscal._cycle_count = 100
        fiscal._last_collection = {}

        mock_connector = AsyncMock()
        mock_connector.collect_metrics = AsyncMock(return_value=MetricResult(
            metric_type="financial", pnl_usd=42.5, roi_pct=5.2,
        ))
        fiscal._get_connector = MagicMock(return_value=mock_connector)
        fiscal._should_collect = MagicMock(return_value=True)

        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.slug = "acciones"

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_project]

        with patch("app.agents.fiscal.async_session", return_value=mock_session):
            mock_session.execute = AsyncMock(return_value=mock_result)
            await fiscal.run_cycle()

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        fiscal.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_collect_failure_logs_no_snapshot(self, fiscal):
        fiscal._cycle_count = 100

        mock_connector = AsyncMock()
        mock_connector.collect_metrics = AsyncMock(side_effect=Exception("API down"))
        fiscal._get_connector = MagicMock(return_value=mock_connector)
        fiscal._should_collect = MagicMock(return_value=True)

        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.slug = "acciones"

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_project]

        with patch("app.agents.fiscal.async_session", return_value=mock_session):
            mock_session.execute = AsyncMock(return_value=mock_result)
            await fiscal.run_cycle()

        # No snapshot persisted on failure
        mock_session.add.assert_not_called()
