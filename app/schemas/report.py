from datetime import datetime

from pydantic import BaseModel


class ProjectSummary(BaseModel):
    slug: str
    name: str
    status: str
    is_healthy: bool
    portfolio_score: float
    latest_metrics: dict = {}
    signal: str = "HOLD"


class PortfolioReport(BaseModel):
    generated_at: datetime
    active_projects: int
    total_projects: int
    projects: list[ProjectSummary]
    recent_decisions: list = []
    recent_alerts: list = []
