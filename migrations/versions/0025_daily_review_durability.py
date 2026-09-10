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


def upgrade() -> None:
    op.add_column(
        "daily_review_runs",
        sa.Column("window_start_utc", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "daily_review_runs",
        sa.Column("window_end_utc", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "daily_review_runs",
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
    )
    op.add_column(
        "daily_review_runs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "daily_review_runs",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "daily_review_runs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "daily_review_runs",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "daily_review_runs",
        sa.Column("last_error_type", sa.String(64), nullable=True),
    )
    op.add_column(
        "daily_review_runs",
        sa.Column("last_error_detail_sanitized", sa.String(255), nullable=True),
    )
    op.add_column(
        "daily_review_runs",
        sa.Column("episode_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "daily_review_runs",
        sa.Column("output_ref", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("daily_review_runs", "output_ref")
    op.drop_column("daily_review_runs", "episode_count")
    op.drop_column("daily_review_runs", "last_error_detail_sanitized")
    op.drop_column("daily_review_runs", "last_error_type")
    op.drop_column("daily_review_runs", "completed_at")
    op.drop_column("daily_review_runs", "started_at")
    op.drop_column("daily_review_runs", "last_attempt_at")
    op.drop_column("daily_review_runs", "attempt_count")
    op.drop_column("daily_review_runs", "status")
    op.drop_column("daily_review_runs", "window_end_utc")
    op.drop_column("daily_review_runs", "window_start_utc")
