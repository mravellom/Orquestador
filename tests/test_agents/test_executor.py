"""Tests for ExecutorAgent: the most dangerous component."""
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from app.connectors.base import ActionResult

# Mock telegram module before importing executor
sys.modules.setdefault("telegram", MagicMock())

from app.agents.executor import ExecutorAgent


@pytest.fixture
def executor():
    with patch("app.agents.executor.async_session"), \
         patch("app.agents.executor.settings") as mock_settings:
        mock_settings.kill_cooling_period_seconds = 300
        mock_settings.kill_requires_human_approval = True
        mock_settings.acciones_api_key = "test"
        agent = ExecutorAgent()
        agent.publish = AsyncMock()
        agent.telegram = AsyncMock()
        agent.docker = AsyncMock()
        return agent


@pytest.fixture
def acciones_project():
    p = MagicMock()
    p.id = 1
    p.slug = "acciones"
    p.name = "Acciones Crypto Trading"
    p.handles_real_money = True
    p.requires_graceful_shutdown = True
    p.docker_compose_path = "/workspace/Acciones/backend"
    p.docker_project_name = "acciones-backend"
    p.status = "ACTIVE"
    return p


@pytest.fixture
def libro_project():
    p = MagicMock()
    p.id = 3
    p.slug = "libro"
    p.name = "Libro KDP"
    p.handles_real_money = False
    p.requires_graceful_shutdown = False
    p.docker_compose_path = "/workspace/Libro"
    p.docker_project_name = "libro"
    p.status = "ACTIVE"
    return p


class TestKillAcciones:
    @pytest.mark.asyncio
    async def test_halts_first(self, executor, acciones_project):
        mock_connector = AsyncMock()
        mock_connector.execute_action = AsyncMock(side_effect=[
            ActionResult(success=True, message="halted"),
            ActionResult(success=True, message="0 open", details={"open_positions": 0}),
        ])

        executor.docker.compose_down = AsyncMock(return_value=(True, "ok"))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=acciones_project)))

        with patch("app.agents.executor.AccionesConnector", return_value=mock_connector), \
             patch("app.agents.executor.async_session", return_value=mock_session):
            log = []
            result = await executor._execute_kill(acciones_project, log)

        assert result is True
        first_call = mock_connector.execute_action.call_args_list[0]
        assert first_call[0][0] == "halt"

    @pytest.mark.asyncio
    async def test_waits_for_positions_to_close(self, executor, acciones_project):
        mock_connector = AsyncMock()
        mock_connector.execute_action = AsyncMock(side_effect=[
            ActionResult(success=True),
            ActionResult(success=True, details={"open_positions": 2}),
            ActionResult(success=True, details={"open_positions": 1}),
            ActionResult(success=True, details={"open_positions": 0}),
        ])

        executor.docker.compose_down = AsyncMock(return_value=(True, "ok"))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=acciones_project)))

        with patch("app.agents.executor.AccionesConnector", return_value=mock_connector), \
             patch("app.agents.executor.async_session", return_value=mock_session), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            log = []
            result = await executor._execute_kill(acciones_project, log)

        assert result is True
        assert mock_connector.execute_action.call_count == 4

    @pytest.mark.asyncio
    async def test_aborts_on_timeout(self, executor, acciones_project):
        mock_connector = AsyncMock()
        mock_connector.execute_action = AsyncMock(side_effect=[
            ActionResult(success=True),
        ] + [
            ActionResult(success=True, details={"open_positions": 2})
            for _ in range(20)
        ])

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("app.agents.executor.AccionesConnector", return_value=mock_connector), \
             patch("app.agents.executor.async_session", return_value=mock_session), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            log = []
            result = await executor._execute_kill(acciones_project, log)

        assert result is False
        executor.telegram.send_alert.assert_called()

    @pytest.mark.asyncio
    async def test_aborts_on_check_fail(self, executor, acciones_project):
        mock_connector = AsyncMock()
        mock_connector.execute_action = AsyncMock(side_effect=[
            ActionResult(success=True),
            ActionResult(success=True, details={"open_positions": -1}),
        ])

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("app.agents.executor.AccionesConnector", return_value=mock_connector), \
             patch("app.agents.executor.async_session", return_value=mock_session):
            log = []
            result = await executor._execute_kill(acciones_project, log)

        assert result is False
        executor.telegram.send_alert.assert_called()

    @pytest.mark.asyncio
    async def test_non_graceful_skips_to_docker(self, executor, libro_project):
        executor.docker.compose_down = AsyncMock(return_value=(True, "ok"))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=libro_project)))

        with patch("app.agents.executor.async_session", return_value=mock_session):
            log = []
            result = await executor._execute_kill(libro_project, log)

        assert result is True
        executor.docker.compose_down.assert_called_once()


class TestPauseResume:
    @pytest.mark.asyncio
    async def test_pause_acciones_uses_api(self, executor, acciones_project):
        mock_connector = AsyncMock()
        mock_connector.execute_action = AsyncMock(return_value=ActionResult(success=True))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=acciones_project)))

        with patch("app.agents.executor.AccionesConnector", return_value=mock_connector), \
             patch("app.agents.executor.async_session", return_value=mock_session):
            log = []
            result = await executor._execute_pause(acciones_project, log)

        assert result is True
        mock_connector.execute_action.assert_called_once_with("halt", {"reason": "Orchestrator PAUSE"})

    @pytest.mark.asyncio
    async def test_pause_other_uses_docker(self, executor, libro_project):
        executor.docker.compose_pause = AsyncMock(return_value=(True, "ok"))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=libro_project)))

        with patch("app.agents.executor.async_session", return_value=mock_session):
            log = []
            result = await executor._execute_pause(libro_project, log)

        assert result is True
        executor.docker.compose_pause.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_acciones_uses_api(self, executor, acciones_project):
        mock_connector = AsyncMock()
        mock_connector.execute_action = AsyncMock(return_value=ActionResult(success=True))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=acciones_project)))

        with patch("app.agents.executor.AccionesConnector", return_value=mock_connector), \
             patch("app.agents.executor.async_session", return_value=mock_session):
            log = []
            result = await executor._execute_resume(acciones_project, log)

        assert result is True

    @pytest.mark.asyncio
    async def test_resume_other_uses_docker(self, executor, libro_project):
        executor.docker.compose_unpause = AsyncMock(return_value=(True, "ok"))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=libro_project)))

        with patch("app.agents.executor.async_session", return_value=mock_session):
            log = []
            result = await executor._execute_resume(libro_project, log)

        assert result is True
        executor.docker.compose_unpause.assert_called_once()


class TestScale:
    @pytest.mark.asyncio
    async def test_scale_sends_telegram_returns_true(self, executor, libro_project):
        log = []
        result = await executor._execute_scale(libro_project, log)
        assert result is True
        executor.telegram.send_alert.assert_called_once()
