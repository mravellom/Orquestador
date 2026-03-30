from datetime import datetime

from pydantic import BaseModel


class DecisionOut(BaseModel):
    id: int
    project_id: int
    decision_type: str
    status: str
    confidence: float | None = None
    reasons: list = []
    rule_triggers: list = []
    requires_human_approval: bool
    approved_by: str | None = None
    proposed_at: datetime
    approved_at: datetime | None = None
    executed_at: datetime | None = None
    execution_log: list = []

    model_config = {"from_attributes": True}


class DecisionApproval(BaseModel):
    approved_by: str = "api:admin"


class DecisionForce(BaseModel):
    project_slug: str
    decision_type: str
    reason: str
