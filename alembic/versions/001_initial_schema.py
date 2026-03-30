"""Initial schema - all 5 tables.

Revision ID: a1b2c3d4e5f6
Revises: None
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision = "a1b2c3d4e5f6"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- projects ---
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(50), unique=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("business_model", sa.String(50), nullable=False),
        sa.Column("base_url", sa.String(255), nullable=False),
        sa.Column("api_key", sa.String(255), nullable=True),
        sa.Column("docker_compose_path", sa.Text, nullable=False),
        sa.Column("docker_project_name", sa.String(100), nullable=False),
        sa.Column("eval_window_hours", sa.Integer, default=720),
        sa.Column("eval_cadence_minutes", sa.Integer, default=60),
        sa.Column("monthly_budget_usd", sa.Numeric(10, 2), default=0),
        sa.Column("status", sa.String(20), default="ACTIVE"),
        sa.Column("handles_real_money", sa.Boolean, default=False),
        sa.Column("requires_graceful_shutdown", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_projects_slug", "projects", ["slug"], unique=True)

    # --- metric_snapshots ---
    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("metric_type", sa.String(50), nullable=False),
        # Financial
        sa.Column("pnl_usd", sa.Numeric(12, 4), nullable=True),
        sa.Column("roi_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("total_capital", sa.Numeric(12, 4), nullable=True),
        sa.Column("available_capital", sa.Numeric(12, 4), nullable=True),
        sa.Column("win_rate_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("drawdown_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(6, 4), nullable=True),
        sa.Column("revenue_usd", sa.Numeric(12, 4), nullable=True),
        # Operational
        sa.Column("active_users", sa.Integer, nullable=True),
        sa.Column("items_processed", sa.Integer, nullable=True),
        sa.Column("false_positive_rate", sa.Numeric(6, 2), nullable=True),
        # Focus cost
        sa.Column("focus_hours_weekly", sa.Numeric(6, 2), nullable=True),
        # Raw extras
        sa.Column("raw_data", JSONB, default=dict),
    )
    op.create_index(
        "ix_metric_snapshots_project_captured",
        "metric_snapshots",
        ["project_id", sa.text("captured_at DESC")],
    )

    # --- health_checks ---
    op.create_table(
        "health_checks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_healthy", sa.Boolean, nullable=False),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("response_ms", sa.Integer, nullable=True),
        sa.Column("database_ok", sa.Boolean, nullable=True),
        sa.Column("redis_ok", sa.Boolean, nullable=True),
        sa.Column("details", JSONB, default=dict),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_health_checks_project_checked",
        "health_checks",
        ["project_id", sa.text("checked_at DESC")],
    )

    # --- decisions ---
    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("decision_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), default="PROPOSED"),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=True),
        sa.Column("reasons", JSONB, default=list),
        sa.Column("rule_triggers", JSONB, default=list),
        sa.Column("requires_human_approval", sa.Boolean, default=False),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_log", JSONB, default=list),
    )
    op.create_index("ix_decisions_status", "decisions", ["status"])

    # --- alerts ---
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("sent_via", sa.String(20), default="telegram"),
        sa.Column("acknowledged", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("decisions")
    op.drop_table("health_checks")
    op.drop_table("metric_snapshots")
    op.drop_table("projects")
