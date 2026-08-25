"""add factor v7 feedback tables

Revision ID: 0011_factor_v7
Revises: 0010_factor_v6
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_factor_v7"
down_revision = "0010_factor_v6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("feedback_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_feedback_symbol", "research_feedback", ["symbol"])
    op.create_table(
        "feedback_validation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("feedback_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feedback_validation_feedback_id", "feedback_validation", ["feedback_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_validation_feedback_id", table_name="feedback_validation")
    op.drop_table("feedback_validation")
    op.drop_index("ix_research_feedback_symbol", table_name="research_feedback")
    op.drop_table("research_feedback")
