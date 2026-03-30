from datetime import datetime

from pydantic import BaseModel


class ProjectOut(BaseModel):
    id: int
    slug: str
    name: str
    business_model: str
    status: str
    handles_real_money: bool
    monthly_budget_usd: float
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectUpdate(BaseModel):
    monthly_budget_usd: float | None = None
    status: str | None = None
    eval_window_hours: int | None = None
    eval_cadence_minutes: int | None = None
