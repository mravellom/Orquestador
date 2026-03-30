from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    business_model: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    docker_compose_path: Mapped[str] = mapped_column(Text, nullable=False)
    docker_project_name: Mapped[str] = mapped_column(String(100), nullable=False)
    eval_window_hours: Mapped[int] = mapped_column(Integer, default=720)
    eval_cadence_minutes: Mapped[int] = mapped_column(Integer, default=60)
    monthly_budget_usd: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    handles_real_money: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_graceful_shutdown: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
