from datetime import datetime

from pydantic import BaseModel


class MetricSnapshotOut(BaseModel):
    id: int
    project_id: int
    captured_at: datetime
    metric_type: str
    pnl_usd: float | None = None
    roi_pct: float | None = None
    total_capital: float | None = None
    available_capital: float | None = None
    win_rate_pct: float | None = None
    drawdown_pct: float | None = None
    sharpe_ratio: float | None = None
    revenue_usd: float | None = None
    active_users: int | None = None
    items_processed: int | None = None
    false_positive_rate: float | None = None
    raw_data: dict = {}

    model_config = {"from_attributes": True}


class HealthCheckOut(BaseModel):
    id: int
    project_id: int
    checked_at: datetime
    is_healthy: bool
    http_status: int | None = None
    response_ms: int | None = None
    database_ok: bool | None = None
    redis_ok: bool | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}
