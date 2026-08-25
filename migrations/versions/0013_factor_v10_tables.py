"""add factor v10 evolution tables

Revision ID: 0013_factor_v10
Revises: 0012_factor_v9
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_factor_v10"
down_revision = "0012_factor_v9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_evolution",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "factor_evolution",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("factor_name", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factor_evolution_factor_name", "factor_evolution", ["factor_name"])
    op.create_table(
        "knowledge_evolution",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("knowledge_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_knowledge_evolution_knowledge_id", "knowledge_evolution", ["knowledge_id"])
    op.create_table(
        "research_optimization",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("research_optimization")
    op.drop_index("ix_knowledge_evolution_knowledge_id", table_name="knowledge_evolution")
    op.drop_table("knowledge_evolution")
    op.drop_index("ix_factor_evolution_factor_name", table_name="factor_evolution")
    op.drop_table("factor_evolution")
    op.drop_table("research_evolution")
