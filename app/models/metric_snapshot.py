from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metric_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Financial
    pnl_usd: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    roi_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    total_capital: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    available_capital: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    win_rate_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    drawdown_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    revenue_usd: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    # Operational
    active_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    false_positive_rate: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)

    # Raw extras
    raw_data: Mapped[dict] = mapped_column(JSONB, default=dict)
