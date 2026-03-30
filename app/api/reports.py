"""Reports API - on-demand report generation."""
from datetime import datetime

from fastapi import APIRouter

router = APIRouter()


@router.get("/reports/daily")
async def daily_report():
    return {"status": "not_implemented", "message": "Will be implemented with Reporter agent"}


@router.get("/reports/weekly")
async def weekly_report():
    return {"status": "not_implemented", "message": "Will be implemented with Reporter agent"}
