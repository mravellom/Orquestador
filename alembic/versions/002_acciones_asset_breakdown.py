"""Add crypto/stocks PnL columns to metric_snapshots.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "metric_snapshots",
        sa.Column("crypto_pnl_usd", sa.Numeric(12, 4), nullable=True),
    )
    op.add_column(
        "metric_snapshots",
        sa.Column("stocks_pnl_usd", sa.Numeric(12, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("metric_snapshots", "stocks_pnl_usd")
    op.drop_column("metric_snapshots", "crypto_pnl_usd")
