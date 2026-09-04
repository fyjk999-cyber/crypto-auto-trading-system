"""add durable trade plans

Revision ID: 0014_trade_plans
Revises: 0013_factor_v10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from crypto_trader.persistence.models import ExactDecimal

revision = "0014_trade_plans"
down_revision = "0013_factor_v10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_plans",
        sa.Column("trade_plan_id", sa.String(64), primary_key=True),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("thesis", sa.String(2000), nullable=False),
        sa.Column("requested_quantity", ExactDecimal(), nullable=False),
        sa.Column("requested_leverage", ExactDecimal(), nullable=True),
        sa.Column("signal_id", sa.String(64), nullable=True),
        sa.Column("risk_decision_id", sa.String(64), nullable=True),
        sa.Column("order_id", sa.String(64), nullable=True),
        sa.Column("position_symbol", sa.String(64), nullable=True),
        sa.Column("terminal_reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("decision_id", name="uq_trade_plans_decision_id"),
        sa.UniqueConstraint("signal_id"),
        sa.UniqueConstraint("risk_decision_id"),
        sa.UniqueConstraint("order_id"),
    )
    op.create_index("ix_trade_plans_symbol", "trade_plans", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_trade_plans_symbol", table_name="trade_plans")
    op.drop_table("trade_plans")
