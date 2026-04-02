from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StrategySnapshot(Base):
    __tablename__ = "strategy_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    strategy_id: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    asset_class: Mapped[str | None] = mapped_column(String(20), nullable=True)

    win_rate_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    pnl_usd: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    trades_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
