"""Reports API - on-demand report generation."""
from datetime import datetime

from fastapi import APIRouter

router = APIRouter()


@router.get("/reports/daily")
async def daily_report():
    """Generate on-demand daily portfolio report."""
    from app.agents.reporter import ReporterAgent
    reporter = ReporterAgent()
    report_text = await reporter.generate_report(hours=24)
    return {"generated_at": datetime.utcnow().isoformat(), "report": report_text}


@router.get("/reports/weekly")
async def weekly_report():
    """Generate on-demand weekly portfolio report."""
    from app.agents.reporter import ReporterAgent
    reporter = ReporterAgent()
    report_text = await reporter.generate_report(hours=168)
    return {"generated_at": datetime.utcnow().isoformat(), "report": report_text}
