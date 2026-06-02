"""Change strategy_id from integer to varchar for UUID support.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "strategy_snapshots",
        "strategy_id",
        existing_type=sa.Integer(),
        type_=sa.String(64),
        existing_nullable=False,
        postgresql_using="strategy_id::varchar",
    )


def downgrade() -> None:
    op.alter_column(
        "strategy_snapshots",
        "strategy_id",
        existing_type=sa.String(64),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="strategy_id::integer",
    )
