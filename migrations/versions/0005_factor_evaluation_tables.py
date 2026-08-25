"""add factor performance, attribution, and decay tables

Revision ID: 0005_factor_eval
Revises: 0004_factor
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_factor_eval"
down_revision = "0004_factor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "factor_performance",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("factor_name", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Numeric(38, 18), nullable=False),
        sa.Column("average_return", sa.Numeric(38, 18), nullable=False),
        sa.Column("sharpe", sa.Numeric(38, 18), nullable=False),
        sa.Column("max_drawdown", sa.Numeric(38, 18), nullable=False),
        sa.Column("profit_factor", sa.Numeric(38, 18), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factor_performance_factor_name", "factor_performance", ["factor_name"])
    op.create_index("ix_factor_performance_symbol", "factor_performance", ["symbol"])
    op.create_table(
        "factor_attribution",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_id", sa.String(64), nullable=False),
        sa.Column("factor_name", sa.String(32), nullable=False),
        sa.Column("contribution", sa.Numeric(38, 18), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factor_attribution_trade_id", "factor_attribution", ["trade_id"])
    op.create_table(
        "factor_decay",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("factor_name", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("old_performance", sa.Numeric(38, 18), nullable=False),
        sa.Column("new_performance", sa.Numeric(38, 18), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factor_decay_factor_name", "factor_decay", ["factor_name"])


def downgrade() -> None:
    op.drop_index("ix_factor_decay_factor_name", table_name="factor_decay")
    op.drop_table("factor_decay")
    op.drop_index("ix_factor_attribution_trade_id", table_name="factor_attribution")
    op.drop_table("factor_attribution")
    op.drop_index("ix_factor_performance_symbol", table_name="factor_performance")
    op.drop_index("ix_factor_performance_factor_name", table_name="factor_performance")
    op.drop_table("factor_performance")
