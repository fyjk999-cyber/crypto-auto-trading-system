"""add factor v6 adaptive intelligence tables

Revision ID: 0010_factor_v6
Revises: 0009_factor_v5
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_factor_v6"
down_revision = "0009_factor_v5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "factor_lifecycle",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("factor_name", sa.String(32), nullable=False),
        sa.Column("old_state", sa.String(16), nullable=False),
        sa.Column("new_state", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factor_lifecycle_factor_name", "factor_lifecycle", ["factor_name"])
    op.create_table(
        "research_priority",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("research_id", sa.String(64), nullable=False),
        sa.Column("priority", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_priority_research_id", "research_priority", ["research_id"])
    op.create_table(
        "factor_importance",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("factor_name", sa.String(32), nullable=False),
        sa.Column("importance", sa.Numeric(38, 18), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factor_importance_factor_name", "factor_importance", ["factor_name"])
    op.create_table(
        "knowledge_decay",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("knowledge_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decay_score", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_knowledge_decay_knowledge_id", "knowledge_decay", ["knowledge_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_decay_knowledge_id", table_name="knowledge_decay")
    op.drop_table("knowledge_decay")
    op.drop_index("ix_factor_importance_factor_name", table_name="factor_importance")
    op.drop_table("factor_importance")
    op.drop_index("ix_research_priority_research_id", table_name="research_priority")
    op.drop_table("research_priority")
    op.drop_index("ix_factor_lifecycle_factor_name", table_name="factor_lifecycle")
    op.drop_table("factor_lifecycle")
