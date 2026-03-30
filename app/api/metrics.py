"""Metrics API - historical metric queries."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.metric_snapshot import MetricSnapshot
from app.models.health_check import HealthCheck
from app.models.project import Project
from app.schemas.metrics import MetricSnapshotOut, HealthCheckOut

router = APIRouter()


@router.get("/metrics/{slug}", response_model=list[MetricSnapshotOut])
async def get_metrics(
    slug: str,
    hours: int = Query(default=24, ge=1, le=8760),
    session: AsyncSession = Depends(get_session),
):
    project = (await session.execute(select(Project).where(Project.slug == slug))).scalar_one_or_none()
    if not project:
        return []

    since = datetime.utcnow() - timedelta(hours=hours)
    result = await session.execute(
        select(MetricSnapshot)
        .where(MetricSnapshot.project_id == project.id, MetricSnapshot.captured_at >= since)
        .order_by(MetricSnapshot.captured_at.desc())
    )
    return result.scalars().all()


@router.get("/metrics/{slug}/latest", response_model=MetricSnapshotOut | None)
async def get_latest_metric(slug: str, session: AsyncSession = Depends(get_session)):
    project = (await session.execute(select(Project).where(Project.slug == slug))).scalar_one_or_none()
    if not project:
        return None

    result = await session.execute(
        select(MetricSnapshot)
        .where(MetricSnapshot.project_id == project.id)
        .order_by(MetricSnapshot.captured_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/health/{slug}", response_model=list[HealthCheckOut])
async def get_health_history(
    slug: str,
    hours: int = Query(default=24, ge=1, le=8760),
    session: AsyncSession = Depends(get_session),
):
    project = (await session.execute(select(Project).where(Project.slug == slug))).scalar_one_or_none()
    if not project:
        return []

    since = datetime.utcnow() - timedelta(hours=hours)
    result = await session.execute(
        select(HealthCheck)
        .where(HealthCheck.project_id == project.id, HealthCheck.checked_at >= since)
        .order_by(HealthCheck.checked_at.desc())
    )
    return result.scalars().all()
