"""enrich durable trade plan lifecycle contract

Revision ID: 0018_trade_plan_contract
Revises: 0017_trade_episodes
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from crypto_trader.persistence.models import ExactDecimal

revision = "0018_trade_plan_contract"
down_revision = "0017_trade_episodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trade_plans", sa.Column("requested_exposure", ExactDecimal(), nullable=True))
    op.add_column("trade_plans", sa.Column("entry_conditions_json", sa.JSON(), nullable=True))
    op.add_column(
        "trade_plans", sa.Column("invalidation_conditions_json", sa.JSON(), nullable=True)
    )
    op.add_column("trade_plans", sa.Column("reduce_conditions_json", sa.JSON(), nullable=True))
    op.add_column("trade_plans", sa.Column("exit_conditions_json", sa.JSON(), nullable=True))
    op.add_column(
        "trade_plans",
        sa.Column("expected_holding_period", sa.String(128), nullable=False, server_default=""),
    )
    op.add_column(
        "trade_plans",
        sa.Column("max_holding_time_seconds", sa.Float(), nullable=False, server_default="86400"),
    )


def downgrade() -> None:
    op.drop_column("trade_plans", "max_holding_time_seconds")
    op.drop_column("trade_plans", "expected_holding_period")
    op.drop_column("trade_plans", "exit_conditions_json")
    op.drop_column("trade_plans", "reduce_conditions_json")
    op.drop_column("trade_plans", "invalidation_conditions_json")
    op.drop_column("trade_plans", "entry_conditions_json")
    op.drop_column("trade_plans", "requested_exposure")
