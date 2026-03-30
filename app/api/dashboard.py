"""Dashboard API - portfolio overview."""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.project import Project
from app.models.health_check import HealthCheck
from app.models.metric_snapshot import MetricSnapshot

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard(session: AsyncSession = Depends(get_session)):
    """Portfolio overview with latest health and metrics per project."""
    projects = (await session.execute(select(Project))).scalars().all()

    dashboard = []
    for p in projects:
        # Latest health check
        health_q = (
            select(HealthCheck)
            .where(HealthCheck.project_id == p.id)
            .order_by(HealthCheck.checked_at.desc())
            .limit(1)
        )
        latest_health = (await session.execute(health_q)).scalar_one_or_none()

        # Latest metric snapshot
        metric_q = (
            select(MetricSnapshot)
            .where(MetricSnapshot.project_id == p.id)
            .order_by(MetricSnapshot.captured_at.desc())
            .limit(1)
        )
        latest_metric = (await session.execute(metric_q)).scalar_one_or_none()

        dashboard.append({
            "slug": p.slug,
            "name": p.name,
            "status": p.status,
            "business_model": p.business_model,
            "handles_real_money": p.handles_real_money,
            "is_healthy": latest_health.is_healthy if latest_health else None,
            "last_health_check": latest_health.checked_at.isoformat() if latest_health else None,
            "response_ms": latest_health.response_ms if latest_health else None,
            "latest_metrics": {
                "pnl_usd": float(latest_metric.pnl_usd) if latest_metric and latest_metric.pnl_usd else None,
                "roi_pct": float(latest_metric.roi_pct) if latest_metric and latest_metric.roi_pct else None,
                "revenue_usd": float(latest_metric.revenue_usd) if latest_metric and latest_metric.revenue_usd else None,
                "win_rate_pct": float(latest_metric.win_rate_pct) if latest_metric and latest_metric.win_rate_pct else None,
                "items_processed": latest_metric.items_processed if latest_metric else None,
            } if latest_metric else {},
        })

    return {
        "total_projects": len(projects),
        "active_projects": sum(1 for p in projects if p.status == "ACTIVE"),
        "projects": dashboard,
    }
