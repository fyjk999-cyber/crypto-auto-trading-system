"""add factor v5 market intelligence tables

Revision ID: 0009_factor_v5
Revises: 0008_factor_v4
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_factor_v5"
down_revision = "0008_factor_v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_intelligence_context",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_market_intelligence_context_symbol",
                    "market_intelligence_context", ["symbol"])
    op.create_table(
        "market_similarity_cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("current_state_json", sa.JSON(), nullable=True),
        sa.Column("historical_state", sa.String(64), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "research_consensus",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("research_ids_json", sa.JSON(), nullable=True),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "knowledge_relations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity_a", sa.String(64), nullable=False),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("entity_b", sa.String(64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("knowledge_relations")
    op.drop_table("research_consensus")
    op.drop_table("market_similarity_cases")
    op.drop_index("ix_market_intelligence_context_symbol",
                  table_name="market_intelligence_context")
    op.drop_table("market_intelligence_context")
