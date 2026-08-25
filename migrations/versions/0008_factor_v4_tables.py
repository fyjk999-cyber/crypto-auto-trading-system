"""add factor v4 autonomous research tables

Revision ID: 0008_factor_v4
Revises: 0007_factor_v3
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_factor_v4"
down_revision = "0007_factor_v3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_anomalies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("severity", sa.Float(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_market_anomalies_symbol", "market_anomalies", ["symbol"])
    op.create_table(
        "research_hypothesis",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("question", sa.String(200), nullable=False),
        sa.Column("factor", sa.String(32), nullable=False),
        sa.Column("logic", sa.String(200), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "research_experiments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hypothesis", sa.String(200), nullable=False),
        sa.Column("dataset", sa.String(64), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "research_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("research_id", sa.String(64), nullable=False, unique=True),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("conclusion", sa.String(500), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("research_reports")
    op.drop_table("research_experiments")
    op.drop_table("research_hypothesis")
    op.drop_index("ix_market_anomalies_symbol", table_name="market_anomalies")
    op.drop_table("market_anomalies")
