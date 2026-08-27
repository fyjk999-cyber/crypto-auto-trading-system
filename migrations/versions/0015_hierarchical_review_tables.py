"""add hierarchical review persistence tables

Revision ID: 0015_hierarchical
Revises: 0014_learning
Create Date: 2026-08-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_hierarchical"
down_revision = "0014_order_contract"
branch_labels = None
depends_on = None


def _weekly_columns():
    return [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("review_id", sa.String(64), nullable=False, unique=True),
        sa.Column("review_type", sa.String(16), nullable=False),
        sa.Column("period_id", sa.String(16), nullable=False),
        sa.Column("starts_at", sa.String(40), nullable=False),
        sa.Column("ends_at", sa.String(40), nullable=False),
        sa.Column("created_at_utc", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("source_review_ids_json", sa.JSON(), nullable=True),
        sa.Column("confirmed_lessons_json", sa.JSON(), nullable=True),
        sa.Column("invalidated_lessons_json", sa.JSON(), nullable=True),
        sa.Column("candidate_lessons_json", sa.JSON(), nullable=True),
        sa.Column("patterns_json", sa.JSON(), nullable=True),
        sa.Column("research_questions_json", sa.JSON(), nullable=True),
        sa.Column("proposals_json", sa.JSON(), nullable=True),
        sa.Column("data_quality", sa.String(16), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table("weekly_review_results", *_weekly_columns())
    op.create_index("ix_weekly_review_results_period_id", "weekly_review_results", ["period_id"])
    op.create_table("monthly_review_results", *_weekly_columns())
    op.create_index("ix_monthly_review_results_period_id", "monthly_review_results", ["period_id"])
    op.create_table("yearly_review_results", *_weekly_columns())
    op.create_index("ix_yearly_review_results_period_id", "yearly_review_results", ["period_id"])
    op.create_table(
        "hierarchical_review_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("review_key", sa.String(64), nullable=False, unique=True),
        sa.Column("review_id", sa.String(64), nullable=False),
        sa.Column("period_type", sa.String(16), nullable=False),
        sa.Column("period_id", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("completed_at", sa.String(40), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hierarchical_review_jobs")
    op.drop_index("ix_yearly_review_results_period_id", table_name="yearly_review_results")
    op.drop_table("yearly_review_results")
    op.drop_index("ix_monthly_review_results_period_id", table_name="monthly_review_results")
    op.drop_table("monthly_review_results")
    op.drop_index("ix_weekly_review_results_period_id", table_name="weekly_review_results")
    op.drop_table("weekly_review_results")
