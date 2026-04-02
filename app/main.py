import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.database import engine, Base

logger = structlog.get_logger()

# Agent references (populated after import)
_agent_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start all agents on startup, stop on shutdown."""
    from app.agents.monitor import MonitorAgent
    from app.agents.fiscal import FiscalAgent
    from app.agents.estratega import EstrategaAgent
    from app.agents.executor import ExecutorAgent
    from app.agents.reporter import ReporterAgent
    from app.agents.approver import ApproverAgent
    from app.connectors.acciones_ws import AccionesWebSocketManager

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Starting orchestrator agents")

    agents = [
        MonitorAgent(),
        FiscalAgent(),
        EstrategaAgent(),
        ExecutorAgent(),
        ReporterAgent(),
        ApproverAgent(),
    ]

    for agent in agents:
        task = asyncio.create_task(agent.start(), name=f"agent-{agent.name}")
        _agent_tasks.append(task)

    logger.info("All agents started", count=len(agents))

    # Start Acciones WebSocket manager (opt-in, non-blocking)
    ws_manager = AccionesWebSocketManager()
    ws_task = asyncio.create_task(ws_manager.start(), name="acciones-ws")
    _agent_tasks.append(ws_task)

    yield

    # Shutdown
    logger.info("Stopping agents")
    for agent in agents:
        await agent.stop()

    await ws_manager.stop()

    for task in _agent_tasks:
        task.cancel()

    await asyncio.gather(*_agent_tasks, return_exceptions=True)
    await engine.dispose()
    logger.info("Orchestrator shutdown complete")


app = FastAPI(
    title="MVP Portfolio Orchestrator",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from app.api.dashboard import router as dashboard_router
from app.api.projects import router as projects_router
from app.api.metrics import router as metrics_router
from app.api.decisions import router as decisions_router
from app.api.agents import router as agents_router
from app.api.reports import router as reports_router

@app.get("/health")
async def health_check():
    """Liveness/readiness probe for the orchestrator."""
    checks = {}

    # DB
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()
        await r.close()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Agents
    agents_alive = sum(1 for t in _agent_tasks if not t.done())
    checks["agents_total"] = len(_agent_tasks)
    checks["agents_alive"] = agents_alive

    healthy = checks.get("database") == "ok" and agents_alive > 0
    return {"status": "healthy" if healthy else "degraded", "checks": checks}


app.include_router(dashboard_router, prefix="/api/v1", tags=["dashboard"])
app.include_router(projects_router, prefix="/api/v1", tags=["projects"])
app.include_router(metrics_router, prefix="/api/v1", tags=["metrics"])
app.include_router(decisions_router, prefix="/api/v1", tags=["decisions"])
app.include_router(agents_router, prefix="/api/v1", tags=["agents"])
app.include_router(reports_router, prefix="/api/v1", tags=["reports"])
