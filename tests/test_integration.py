"""Integration test: full scenario of Acciones crash -> KILL flow."""
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.engine.rules import ProjectMetrics, eval_roi_negative_30d, eval_drawdown_critical
from app.engine.scoring import calculate_portfolio_score, evaluate_signal_with_hysteresis
from app.connectors.base import ActionResult

sys.modules.setdefault("telegram", MagicMock())


class TestFullScenarioAccionesCrash:
    """
    Simulate: Acciones has ROI=-25%, drawdown=18%
    Expected flow:
    1. Rules fire (ROI negative -> KILL, drawdown -> PAUSE)
    2. PAUSE takes priority (more immediate)
    3. Score should be very low
    4. Hysteresis with 3 low cycles -> confirms KILL signal
    5. Executor halts -> waits for positions -> docker down
    """

    def test_rules_fire_correctly(self):
        metrics = ProjectMetrics(
            slug="acciones",
            business_model="trading",
            handles_real_money=True,
            roi_pct=-25,
            drawdown_pct=18,
            pnl_usd=-500,
        )

        roi_result = eval_roi_negative_30d(metrics)
        assert roi_result.fired is True
        assert roi_result.decision_type == "KILL"
        assert roi_result.requires_human is True

        dd_result = eval_drawdown_critical(metrics)
        assert dd_result.fired is True
        assert dd_result.decision_type == "PAUSE"

    def test_score_is_very_low(self):
        score = calculate_portfolio_score(
            is_healthy=True,
            roi_pct=-25,
            roi_trend=-0.5,
            win_rate_pct=30,
            drawdown_pct=18,
            revenue_usd=None,
            items_processed=None,
            false_positive_rate=None,
        )
        assert score < 30  # KILL candidate

    def test_hysteresis_confirms_kill_after_3_cycles(self):
        # 3 consecutive cycles with score < 25
        history = [22, 20, 18]
        signal = evaluate_signal_with_hysteresis(18, history, "HOLD")
        assert signal == "KILL"

    @pytest.mark.asyncio
    async def test_executor_kill_full_flow(self):
        """End-to-end: halt -> close positions -> docker down -> KILLED."""
        mock_connector = AsyncMock()
        mock_connector.execute_action = AsyncMock(side_effect=[
            ActionResult(success=True, message="halted"),
            ActionResult(success=True, details={"open_positions": 2}),
            ActionResult(success=True, details={"open_positions": 0}),
        ])

        project = MagicMock()
        project.id = 1
        project.slug = "acciones"
        project.name = "Acciones"
        project.requires_graceful_shutdown = True
        project.docker_compose_path = "/workspace/Acciones/backend"
        project.docker_project_name = "acciones-backend"

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=project)))

        with patch("app.agents.executor.async_session", return_value=mock_session), \
             patch("app.agents.executor.AccionesConnector", return_value=mock_connector), \
             patch("app.agents.executor.settings") as mock_settings, \
             patch("app.agents.executor.TelegramNotifier"), \
             patch("asyncio.sleep", new_callable=AsyncMock):

            mock_settings.acciones_api_key = "test"
            mock_settings.kill_cooling_period_seconds = 0
            mock_settings.kill_requires_human_approval = False

            from app.agents.executor import ExecutorAgent
            executor = ExecutorAgent()
            executor.publish = AsyncMock()
            executor.telegram = AsyncMock()
            executor.docker = AsyncMock()
            executor.docker.compose_down = AsyncMock(return_value=(True, "stopped"))

            log = []
            result = await executor._execute_kill(project, log)

        assert result is True
        # Verify sequence: halt called, positions checked, docker down called
        assert mock_connector.execute_action.call_count == 3
        executor.docker.compose_down.assert_called_once()
        executor.telegram.send_alert.assert_called()  # KILLED alert
