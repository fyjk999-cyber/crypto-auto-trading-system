"""add factor registry, values, and snapshots tables

Revision ID: 0004_factor
Revises: 0003_ai_memory
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_factor"
down_revision = "0003_ai_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "factor_registry",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("factor_id", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "factor_values",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("factor", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("value", sa.Numeric(38, 18), nullable=False),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factor_values_symbol", "factor_values", ["symbol"])
    op.create_table(
        "factor_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factor_snapshots_symbol", "factor_snapshots", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_factor_snapshots_symbol", table_name="factor_snapshots")
    op.drop_table("factor_snapshots")
    op.drop_index("ix_factor_values_symbol", table_name="factor_values")
    op.drop_table("factor_values")
    op.drop_table("factor_registry")
