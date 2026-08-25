"""add factor v3 regime/confidence/combination tables

Revision ID: 0007_factor_v3
Revises: 0006_factor_catalog
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_factor_v3"
down_revision = "0006_factor_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_regime_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("regime", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_market_regime_history_symbol", "market_regime_history", ["symbol"])
    op.create_table(
        "factor_regime_performance",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("factor_name", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("regime", sa.String(32), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Numeric(38, 18), nullable=False),
        sa.Column("sharpe", sa.Numeric(38, 18), nullable=False),
        sa.Column("return_value", sa.Numeric(38, 18), nullable=False),
        sa.Column("drawdown", sa.Numeric(38, 18), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factor_regime_performance_factor_name", "factor_regime_performance", ["factor_name"])
    op.create_table(
        "factor_confidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("factor_name", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=False),
        sa.Column("historical_reliability", sa.Numeric(38, 18), nullable=False),
        sa.Column("regime_match", sa.Numeric(38, 18), nullable=False),
        sa.Column("decay_penalty", sa.Numeric(38, 18), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factor_confidence_factor_name", "factor_confidence", ["factor_name"])
    op.create_table(
        "factor_combinations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("factors_json", sa.JSON(), nullable=True),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("performance_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("factor_combinations")
    op.drop_index("ix_factor_confidence_factor_name", table_name="factor_confidence")
    op.drop_table("factor_confidence")
    op.drop_index("ix_factor_regime_performance_factor_name", table_name="factor_regime_performance")
    op.drop_table("factor_regime_performance")
    op.drop_index("ix_market_regime_history_symbol", table_name="market_regime_history")
    op.drop_table("market_regime_history")
