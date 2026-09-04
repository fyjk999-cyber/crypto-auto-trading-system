"""add canonical position lifecycle lineage

Revision ID: 0016_position_lifecycle
Revises: 0015_llm_decisions
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from crypto_trader.persistence.models import ExactDecimal

revision = "0016_position_lifecycle"
down_revision = "0015_llm_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("metadata_json", sa.JSON(), nullable=True))
    op.add_column(
        "positions_projection",
        sa.Column("instrument_type", sa.String(24), nullable=False, server_default="SPOT"),
    )
    op.add_column(
        "positions_projection",
        sa.Column("contract_size", ExactDecimal(), nullable=False, server_default="1"),
    )
    op.add_column(
        "positions_projection",
        sa.Column("contract_multiplier", ExactDecimal(), nullable=False, server_default="1"),
    )
    op.add_column(
        "trade_plans", sa.Column("latest_position_decision_id", sa.String(64), nullable=True)
    )
    op.add_column("trade_plans", sa.Column("exit_decision_id", sa.String(64), nullable=True))
    op.add_column(
        "trade_plans", sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "trade_plans", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_trade_plans_latest_position_decision_id",
        "trade_plans",
        ["latest_position_decision_id"],
    )
    op.create_index(
        "ix_trade_plans_exit_decision_id", "trade_plans", ["exit_decision_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_trade_plans_exit_decision_id", table_name="trade_plans")
    op.drop_index("ix_trade_plans_latest_position_decision_id", table_name="trade_plans")
    op.drop_column("trade_plans", "closed_at")
    op.drop_column("trade_plans", "opened_at")
    op.drop_column("trade_plans", "exit_decision_id")
    op.drop_column("trade_plans", "latest_position_decision_id")
    op.drop_column("positions_projection", "contract_multiplier")
    op.drop_column("positions_projection", "contract_size")
    op.drop_column("positions_projection", "instrument_type")
    op.drop_column("orders", "metadata_json")
