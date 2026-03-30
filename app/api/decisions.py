"""Decisions API - manage and approve decisions."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.decision import Decision
from app.schemas.decision import DecisionOut, DecisionApproval

router = APIRouter()


@router.get("/decisions", response_model=list[DecisionOut])
async def list_decisions(
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(Decision).order_by(Decision.proposed_at.desc()).limit(50)
    if status:
        query = query.where(Decision.status == status)
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/decisions/{decision_id}", response_model=DecisionOut)
async def get_decision(decision_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    return decision


@router.post("/decisions/{decision_id}/approve")
async def approve_decision(
    decision_id: int,
    approval: DecisionApproval,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    if decision.status != "PROPOSED":
        raise HTTPException(status_code=400, detail=f"Decision is {decision.status}, not PROPOSED")

    decision.status = "APPROVED"
    decision.approved_by = approval.approved_by
    decision.approved_at = datetime.utcnow()
    await session.commit()
    return {"id": decision_id, "status": "APPROVED"}


@router.post("/decisions/{decision_id}/reject")
async def reject_decision(decision_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    decision.status = "REJECTED"
    await session.commit()
    return {"id": decision_id, "status": "REJECTED"}
