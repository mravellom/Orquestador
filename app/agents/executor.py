"""Executor Agent: executes approved decisions (SCALE, KILL, PAUSE, RESUME)."""
import asyncio
import json
from datetime import datetime

import redis.asyncio as aioredis
import structlog
from sqlalchemy import select

from app.agents.base import BaseAgent
from app.config import settings, PROJECT_REGISTRY
from app.connectors.acciones import AccionesConnector
from app.database import async_session
from app.docker_control.manager import DockerManager
from app.models.decision import Decision
from app.models.project import Project
from app.notifications.telegram import TelegramNotifier

logger = structlog.get_logger()


class ExecutorAgent(BaseAgent):
    name = "executor"
    cadence_seconds = 15  # Check for approved decisions frequently
    publish_channel = "orq:executions"

    def __init__(self):
        super().__init__()
        self.docker = DockerManager()
        self.telegram = TelegramNotifier()

    async def run_cycle(self):
        """Find approved decisions and execute them."""
        async with async_session() as session:
            result = await session.execute(
                select(Decision)
                .where(Decision.status == "APPROVED")
                .order_by(Decision.approved_at.asc())
            )
            decisions = result.scalars().all()

        for decision in decisions:
            await self._execute_decision(decision)

        # Also auto-approve non-human decisions that are still PROPOSED
        async with async_session() as session:
            result = await session.execute(
                select(Decision)
                .where(
                    Decision.status == "PROPOSED",
                    Decision.requires_human_approval == False,
                )
                .order_by(Decision.proposed_at.asc())
            )
            auto_decisions = result.scalars().all()

        for decision in auto_decisions:
            # Apply cooling period
            if decision.proposed_at:
                elapsed = (datetime.utcnow() - decision.proposed_at.replace(tzinfo=None)).total_seconds()
                if elapsed < settings.kill_cooling_period_seconds and decision.decision_type == "KILL":
                    continue

            async with async_session() as session:
                d = (await session.execute(select(Decision).where(Decision.id == decision.id))).scalar_one()
                d.status = "APPROVED"
                d.approved_by = "auto"
                d.approved_at = datetime.utcnow()
                await session.commit()

            await self._execute_decision(decision)

    async def _execute_decision(self, decision: Decision):
        """Execute a single decision."""
        async with async_session() as session:
            project = (await session.execute(
                select(Project).where(Project.id == decision.project_id)
            )).scalar_one_or_none()

        if not project:
            logger.error("Project not found for decision", decision_id=decision.id)
            return

        logger.warning(
            "Executing decision",
            project=project.slug,
            type=decision.decision_type,
            decision_id=decision.id,
        )

        execution_log = []
        success = False

        try:
            if decision.decision_type == "KILL":
                success = await self._execute_kill(project, execution_log)
            elif decision.decision_type == "PAUSE":
                success = await self._execute_pause(project, execution_log)
            elif decision.decision_type == "RESUME":
                success = await self._execute_resume(project, execution_log)
            elif decision.decision_type == "SCALE":
                success = await self._execute_scale(project, execution_log)
            elif decision.decision_type == "PIVOT":
                # Pivot is informational - notify and mark done
                execution_log.append("PIVOT recommendation sent to Telegram")
                await self.telegram.send_alert(
                    "WARNING", project.name,
                    f"PIVOT recommended: {decision.reasons}",
                )
                success = True
        except Exception as e:
            execution_log.append(f"ERROR: {str(e)}")
            logger.error("Decision execution failed", error=str(e))

        # Update decision status
        new_status = "EXECUTED" if success else "FAILED"
        async with async_session() as session:
            d = (await session.execute(select(Decision).where(Decision.id == decision.id))).scalar_one()
            d.status = new_status
            d.executed_at = datetime.utcnow()
            d.execution_log = execution_log
            await session.commit()

        await self.publish("execution_complete", {
            "decision_id": decision.id,
            "project_slug": project.slug,
            "decision_type": decision.decision_type,
            "status": new_status,
            "log": execution_log,
        })

    async def _execute_kill(self, project: Project, log: list) -> bool:
        """Kill a project. Special handling for real-money projects."""

        # Safety: graceful shutdown for Acciones
        if project.requires_graceful_shutdown:
            log.append("Project requires graceful shutdown")

            # Get connector to check positions
            cfg = next((c for c in PROJECT_REGISTRY if c.slug == project.slug), None)
            if cfg and project.slug == "acciones":
                api_key = getattr(settings, cfg.api_key_env, "") if cfg.api_key_env else None
                connector = AccionesConnector(base_url=cfg.base_url, api_key=api_key or None)

                # Halt trading first
                result = await connector.execute_action("halt", {"reason": "Orchestrator KILL"})
                log.append(f"Halt trading: {'OK' if result.success else result.message}")

                # Wait for positions to close
                for attempt in range(20):  # 20 * 30s = 10 minutes max
                    pos_result = await connector.execute_action("check_positions")
                    open_pos = pos_result.details.get("open_positions", -1)
                    log.append(f"Check positions (attempt {attempt + 1}): {open_pos} open")

                    if open_pos == 0:
                        break
                    if open_pos == -1:
                        log.append("Could not check positions, aborting kill")
                        await self.telegram.send_alert(
                            "EMERGENCY", project.name,
                            "KILL aborted: cannot verify open positions. Manual intervention required.",
                        )
                        return False

                    await asyncio.sleep(30)
                else:
                    log.append("Timeout waiting for positions to close, aborting kill")
                    await self.telegram.send_alert(
                        "EMERGENCY", project.name,
                        "KILL aborted: positions still open after 10 min. Manual intervention required.",
                    )
                    return False

        # Docker compose down
        success, output = await self.docker.compose_down(
            project.docker_compose_path, project.docker_project_name,
        )
        log.append(f"Docker compose down: {'OK' if success else output[:200]}")

        if success:
            async with async_session() as session:
                p = (await session.execute(select(Project).where(Project.id == project.id))).scalar_one()
                p.status = "KILLED"
                await session.commit()
            log.append("Project status set to KILLED")
            await self.telegram.send_alert("CRITICAL", project.name, "Project has been KILLED by orchestrator.")

        return success

    async def _execute_pause(self, project: Project, log: list) -> bool:
        """Pause a project."""
        # For Acciones, use the halt endpoint
        if project.slug == "acciones":
            cfg = next((c for c in PROJECT_REGISTRY if c.slug == "acciones"), None)
            if cfg:
                api_key = getattr(settings, cfg.api_key_env, "") if cfg.api_key_env else None
                connector = AccionesConnector(base_url=cfg.base_url, api_key=api_key or None)
                result = await connector.execute_action("halt", {"reason": "Orchestrator PAUSE"})
                log.append(f"Halt via API: {'OK' if result.success else result.message}")
                if result.success:
                    async with async_session() as session:
                        p = (await session.execute(select(Project).where(Project.id == project.id))).scalar_one()
                        p.status = "PAUSED"
                        await session.commit()
                return result.success

        # For others, docker compose pause
        success, output = await self.docker.compose_pause(
            project.docker_compose_path, project.docker_project_name,
        )
        log.append(f"Docker compose pause: {'OK' if success else output[:200]}")

        if success:
            async with async_session() as session:
                p = (await session.execute(select(Project).where(Project.id == project.id))).scalar_one()
                p.status = "PAUSED"
                await session.commit()

        return success

    async def _execute_resume(self, project: Project, log: list) -> bool:
        """Resume a paused project."""
        if project.slug == "acciones":
            cfg = next((c for c in PROJECT_REGISTRY if c.slug == "acciones"), None)
            if cfg:
                api_key = getattr(settings, cfg.api_key_env, "") if cfg.api_key_env else None
                connector = AccionesConnector(base_url=cfg.base_url, api_key=api_key or None)
                result = await connector.execute_action("resume")
                log.append(f"Resume via API: {'OK' if result.success else result.message}")
                if result.success:
                    async with async_session() as session:
                        p = (await session.execute(select(Project).where(Project.id == project.id))).scalar_one()
                        p.status = "ACTIVE"
                        await session.commit()
                return result.success

        success, output = await self.docker.compose_unpause(
            project.docker_compose_path, project.docker_project_name,
        )
        log.append(f"Docker compose unpause: {'OK' if success else output[:200]}")

        if success:
            async with async_session() as session:
                p = (await session.execute(select(Project).where(Project.id == project.id))).scalar_one()
                p.status = "ACTIVE"
                await session.commit()

        return success

    async def _execute_scale(self, project: Project, log: list) -> bool:
        """Scale recommendation - mostly informational for now."""
        log.append(f"SCALE recommendation for {project.slug}")
        await self.telegram.send_alert(
            "INFO", project.name,
            f"SCALE recommended. Consider increasing resources or capital for {project.name}.",
        )
        return True
