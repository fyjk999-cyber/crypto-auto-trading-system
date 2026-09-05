"""add factual canonical trade episodes

Revision ID: 0017_trade_episodes
Revises: 0016_position_lifecycle
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from crypto_trader.persistence.models import ExactDecimal

revision = "0017_trade_episodes"
down_revision = "0016_position_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_episodes",
        sa.Column("episode_id", sa.String(64), primary_key=True),
        sa.Column("trade_plan_id", sa.String(64), nullable=False, unique=True),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("entry_decision_id", sa.String(64), nullable=False),
        sa.Column("position_decision_ids_json", sa.JSON(), nullable=True),
        sa.Column("order_ids_json", sa.JSON(), nullable=True),
        sa.Column("fill_ids_json", sa.JSON(), nullable=True),
        sa.Column("entry_price", ExactDecimal(), nullable=False),
        sa.Column("exit_price", ExactDecimal(), nullable=False),
        sa.Column("opened_quantity", ExactDecimal(), nullable=False),
        sa.Column("closed_quantity", ExactDecimal(), nullable=False),
        sa.Column("leverage", ExactDecimal(), nullable=False),
        sa.Column("fees", ExactDecimal(), nullable=False, server_default="0"),
        sa.Column("funding_pnl", ExactDecimal(), nullable=False, server_default="0"),
        sa.Column("gross_pnl", ExactDecimal(), nullable=False),
        sa.Column("net_pnl", ExactDecimal(), nullable=False),
        sa.Column("holding_time_seconds", sa.Float(), nullable=False),
        sa.Column("entry_market_regime", sa.String(64), nullable=False),
        sa.Column("terminal_reason", sa.String(255), nullable=False),
        sa.Column("factual", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trade_episodes_trade_plan_id", "trade_episodes", ["trade_plan_id"])
    op.create_index("ix_trade_episodes_symbol", "trade_episodes", ["symbol"])
    op.create_index("ix_trade_episodes_entry_decision_id", "trade_episodes", ["entry_decision_id"])
    op.create_index("ix_trade_episodes_closed_at", "trade_episodes", ["closed_at"])


def downgrade() -> None:
    op.drop_index("ix_trade_episodes_closed_at", table_name="trade_episodes")
    op.drop_index("ix_trade_episodes_entry_decision_id", table_name="trade_episodes")
    op.drop_index("ix_trade_episodes_symbol", table_name="trade_episodes")
    op.drop_index("ix_trade_episodes_trade_plan_id", table_name="trade_episodes")
    op.drop_table("trade_episodes")
