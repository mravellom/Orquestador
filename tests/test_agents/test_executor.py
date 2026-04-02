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
            ActionResult(success=True, message="halted"),                          # halt
            ActionResult(success=True, details={"positions": []}),                 # list_positions
            ActionResult(success=True, message="0 open", details={"open_positions": 0}),  # check_positions
        ])

        executor.docker.compose_down = AsyncMock(return_value=(True, "ok"))
        executor._get_acciones_connector = MagicMock(return_value=mock_connector)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=acciones_project)))

        with patch("app.agents.executor.async_session", return_value=mock_session):
            log = []
            result = await executor._execute_kill(acciones_project, log)

        assert result is True
        first_call = mock_connector.execute_action.call_args_list[0]
        assert first_call[0][0] == "halt"

    @pytest.mark.asyncio
    async def test_aborts_on_timeout(self, executor, acciones_project):
        mock_connector = AsyncMock()
        mock_connector.execute_action = AsyncMock(side_effect=[
            ActionResult(success=True),                                            # halt
            ActionResult(success=True, details={"positions": [{"id": 1}]}),       # list_positions
            ActionResult(success=True, details={"position_id": 1}),               # close_position
        ] + [
            ActionResult(success=True, details={"open_positions": 2})             # check_positions (20x)
            for _ in range(20)
        ])

        executor._get_acciones_connector = MagicMock(return_value=mock_connector)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("app.agents.executor.async_session", return_value=mock_session), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            log = []
            result = await executor._execute_kill(acciones_project, log)

        assert result is False
        executor.telegram.send_alert.assert_called()

    @pytest.mark.asyncio
    async def test_aborts_on_check_fail(self, executor, acciones_project):
        mock_connector = AsyncMock()
        mock_connector.execute_action = AsyncMock(side_effect=[
            ActionResult(success=True),                                            # halt
            ActionResult(success=True, details={"positions": []}),                 # list_positions
            ActionResult(success=True, details={"open_positions": -1}),            # check_positions
        ])

        executor._get_acciones_connector = MagicMock(return_value=mock_connector)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("app.agents.executor.async_session", return_value=mock_session):
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
        executor._get_acciones_connector = MagicMock(return_value=mock_connector)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=acciones_project)))

        with patch("app.agents.executor.async_session", return_value=mock_session):
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
        executor._get_acciones_connector = MagicMock(return_value=mock_connector)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=acciones_project)))

        with patch("app.agents.executor.async_session", return_value=mock_session):
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


class TestRunCycleAutoApprove:
    """Tests for the auto-approve flow in run_cycle."""

    @pytest.mark.asyncio
    async def test_auto_approves_non_human_proposed(self, executor):
        """PROPOSED decisions without requires_human should be auto-approved."""
        decision = MagicMock()
        decision.id = 1
        decision.status = "PROPOSED"
        decision.requires_human_approval = False
        decision.decision_type = "PAUSE"
        decision.proposed_at = datetime.utcnow() - timedelta(minutes=10)
        decision.project_id = 1

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        # First query: APPROVED decisions - empty
        approved_result = MagicMock()
        approved_result.scalars.return_value.all.return_value = []
        # Second query: PROPOSED non-human decisions
        proposed_result = MagicMock()
        proposed_result.scalars.return_value.all.return_value = [decision]
        # Third query: re-fetch decision for update
        refetch_result = MagicMock()
        refetch_result.scalar_one.return_value = decision

        mock_session.execute = AsyncMock(side_effect=[approved_result, proposed_result, refetch_result])

        executor._execute_decision = AsyncMock()

        with patch("app.agents.executor.async_session", return_value=mock_session):
            await executor.run_cycle()

        # Decision should be auto-approved
        assert decision.status == "APPROVED"
        assert decision.approved_by == "auto"
        executor._execute_decision.assert_called_once()

    @pytest.mark.asyncio
    async def test_kill_cooling_period_blocks(self, executor):
        """KILL decisions within cooling period should NOT be auto-approved."""
        decision = MagicMock()
        decision.id = 1
        decision.status = "PROPOSED"
        decision.requires_human_approval = False
        decision.decision_type = "KILL"
        decision.proposed_at = datetime.utcnow() - timedelta(seconds=60)  # Only 60s ago, cooling=300s
        decision.project_id = 1

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        approved_result = MagicMock()
        approved_result.scalars.return_value.all.return_value = []
        proposed_result = MagicMock()
        proposed_result.scalars.return_value.all.return_value = [decision]

        mock_session.execute = AsyncMock(side_effect=[approved_result, proposed_result])

        executor._execute_decision = AsyncMock()

        with patch("app.agents.executor.async_session", return_value=mock_session):
            await executor.run_cycle()

        # Should NOT be executed due to cooling period
        executor._execute_decision.assert_not_called()

    @pytest.mark.asyncio
    async def test_kill_after_cooling_period_proceeds(self, executor):
        """KILL decisions past cooling period should be auto-approved."""
        decision = MagicMock()
        decision.id = 1
        decision.status = "PROPOSED"
        decision.requires_human_approval = False
        decision.decision_type = "KILL"
        decision.proposed_at = datetime.utcnow() - timedelta(seconds=600)  # 600s ago, cooling=300s
        decision.project_id = 1

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        approved_result = MagicMock()
        approved_result.scalars.return_value.all.return_value = []
        proposed_result = MagicMock()
        proposed_result.scalars.return_value.all.return_value = [decision]
        refetch_result = MagicMock()
        refetch_result.scalar_one.return_value = decision

        mock_session.execute = AsyncMock(side_effect=[approved_result, proposed_result, refetch_result])

        executor._execute_decision = AsyncMock()

        with patch("app.agents.executor.async_session", return_value=mock_session):
            await executor.run_cycle()

        assert decision.status == "APPROVED"
        executor._execute_decision.assert_called_once()


class TestExecuteDecisionRouting:
    """Tests for _execute_decision routing and status updates."""

    @pytest.mark.asyncio
    async def test_pivot_sends_alert_no_docker(self, executor):
        """PIVOT decisions should send Telegram alert but not touch Docker."""
        decision = MagicMock()
        decision.id = 1
        decision.decision_type = "PIVOT"
        decision.project_id = 1
        decision.reasons = ["Stagnant metrics"]
        decision.status = "APPROVED"

        project = MagicMock()
        project.id = 1
        project.slug = "casas"
        project.name = "Casas"

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        # Query for project
        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        # Query for decision update
        decision_result = MagicMock()
        decision_result.scalar_one.return_value = decision

        mock_session.execute = AsyncMock(side_effect=[project_result, decision_result])

        with patch("app.agents.executor.async_session", return_value=mock_session):
            await executor._execute_decision(decision)

        assert decision.status == "EXECUTED"
        executor.telegram.send_alert.assert_called()
        executor.docker.compose_down.assert_not_called()

    @pytest.mark.asyncio
    async def test_docker_down_failure_marks_failed(self, executor):
        """When docker compose down fails, decision should be FAILED."""
        decision = MagicMock()
        decision.id = 1
        decision.decision_type = "KILL"
        decision.project_id = 1
        decision.status = "APPROVED"

        project = MagicMock()
        project.id = 1
        project.slug = "libro"
        project.name = "Libro"
        project.requires_graceful_shutdown = False
        project.docker_compose_path = "/workspace/Libro"
        project.docker_project_name = "libro"

        executor.docker.compose_down = AsyncMock(return_value=(False, "error: container not found"))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        decision_result = MagicMock()
        decision_result.scalar_one.return_value = decision

        mock_session.execute = AsyncMock(side_effect=[project_result, decision_result])

        with patch("app.agents.executor.async_session", return_value=mock_session):
            await executor._execute_decision(decision)

        assert decision.status == "FAILED"

    @pytest.mark.asyncio
    async def test_exception_in_action_marks_failed(self, executor):
        """When an action throws an exception, decision should be FAILED."""
        decision = MagicMock()
        decision.id = 1
        decision.decision_type = "KILL"
        decision.project_id = 1
        decision.status = "APPROVED"

        project = MagicMock()
        project.id = 1
        project.slug = "libro"
        project.name = "Libro"
        project.requires_graceful_shutdown = False

        # Make _execute_kill raise
        executor._execute_kill = AsyncMock(side_effect=Exception("Docker socket unavailable"))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        decision_result = MagicMock()
        decision_result.scalar_one.return_value = decision

        mock_session.execute = AsyncMock(side_effect=[project_result, decision_result])

        with patch("app.agents.executor.async_session", return_value=mock_session):
            await executor._execute_decision(decision)

        assert decision.status == "FAILED"
        # execution_log should contain the error
        assert any("Docker socket" in str(entry) for entry in decision.execution_log)

    @pytest.mark.asyncio
    async def test_project_not_found_returns_early(self, executor):
        """When project is not found, should return without executing."""
        decision = MagicMock()
        decision.id = 1
        decision.decision_type = "KILL"
        decision.project_id = 999

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = None

        mock_session.execute = AsyncMock(return_value=project_result)

        with patch("app.agents.executor.async_session", return_value=mock_session):
            await executor._execute_decision(decision)

        # No publish should happen since we returned early
        executor.publish.assert_not_called()
