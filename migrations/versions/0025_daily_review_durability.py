"""durable daily review execution state

Revision ID: 0025_daily_review_durability
Revises: 0024_equity_snapshots
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_daily_review_durability"
down_revision = "0024_equity_snapshots"
branch_labels = None
depends_on = None


def _columns() -> dict[str, sa.Column]:
    return {
        "window_start_utc": sa.Column(
            "window_start_utc", sa.DateTime(timezone=True), nullable=True
        ),
        "window_end_utc": sa.Column(
            "window_end_utc", sa.DateTime(timezone=True), nullable=True
        ),
        "status": sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        "attempt_count": sa.Column(
            "attempt_count", sa.Integer(), nullable=False, server_default="0"
        ),
        "last_attempt_at": sa.Column(
            "last_attempt_at", sa.DateTime(timezone=True), nullable=True
        ),
        "started_at": sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        "completed_at": sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        "last_error_type": sa.Column("last_error_type", sa.String(64), nullable=True),
        "last_error_detail_sanitized": sa.Column(
            "last_error_detail_sanitized", sa.String(255), nullable=True
        ),
        "episode_count": sa.Column(
            "episode_count", sa.Integer(), nullable=False, server_default="0"
        ),
        "output_ref": sa.Column("output_ref", sa.String(128), nullable=True),
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "daily_review_runs" not in tables:
        op.create_table(
            "daily_review_runs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("review_date", sa.String(16), nullable=False, unique=True),
            sa.Column("daily_pnl", sa.String(80), nullable=False, server_default="0"),
            sa.Column("long_pnl", sa.String(80), nullable=False, server_default="0"),
            sa.Column("short_pnl", sa.String(80), nullable=False, server_default="0"),
            sa.Column("trade_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("win_rate", sa.String(80), nullable=False, server_default="0"),
            sa.Column("profit_factor", sa.String(80), nullable=False, server_default="0"),
            sa.Column("expectancy", sa.String(80), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            *_columns().values(),
        )
        return
    existing = {c["name"] for c in inspector.get_columns("daily_review_runs")}
    for name, column in _columns().items():
        if name not in existing:
            op.add_column("daily_review_runs", column)


def downgrade() -> None:
    bind = op.get_bind()
    if "daily_review_runs" not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_table("daily_review_runs")
