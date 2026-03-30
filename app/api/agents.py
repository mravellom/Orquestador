"""Agents API - status and control of the 5 agents."""
from fastapi import APIRouter

router = APIRouter()

# Agent instances will be populated from main.py lifespan
_agents: dict = {}


def register_agents(agents: list):
    for a in agents:
        _agents[a.name] = a


@router.get("/agents/status")
async def agents_status():
    return {name: agent.get_status() for name, agent in _agents.items()}


@router.post("/agents/{name}/trigger")
async def trigger_agent(name: str):
    agent = _agents.get(name)
    if not agent:
        return {"error": f"Agent {name} not found"}
    try:
        await agent.run_cycle()
        return {"agent": name, "status": "cycle_triggered"}
    except Exception as e:
        return {"agent": name, "error": str(e)}
