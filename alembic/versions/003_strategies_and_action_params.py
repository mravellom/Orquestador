"""Add strategy_snapshots table, action_params to decisions, widen decision_type.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- strategy_snapshots table ---
    op.create_table(
        "strategy_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("strategy_id", sa.Integer, nullable=False),
        sa.Column("strategy_name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("asset_class", sa.String(20), nullable=True),
        sa.Column("win_rate_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("pnl_usd", sa.Numeric(12, 4), nullable=True),
        sa.Column("trades_count", sa.Integer, nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(6, 4), nullable=True),
    )
    op.create_index(
        "ix_strategy_snapshots_project_captured",
        "strategy_snapshots",
        ["project_id", sa.text("captured_at DESC")],
    )

    # --- action_params on decisions ---
    op.add_column(
        "decisions",
        sa.Column("action_params", JSONB, server_default="{}"),
    )

    # --- widen decision_type from 20 to 30 chars ---
    # DEACTIVATE_STRATEGY is 21 chars, ACTIVATE_STRATEGY is 17
    op.alter_column(
        "decisions",
        "decision_type",
        type_=sa.String(30),
        existing_type=sa.String(20),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "decisions",
        "decision_type",
        type_=sa.String(20),
        existing_type=sa.String(30),
        existing_nullable=False,
    )
    op.drop_column("decisions", "action_params")
    op.drop_table("strategy_snapshots")
