"""Growth V2 daily frozen TOP-10 opportunities (Phase 5).

Adds `daily_opportunity_top10`: the decision-time-sorted Top-10 snapshot per
trading day. Rows are immutable after the day is frozen so later outcomes can
never re-select the list (no hindsight).

Revision ID: 0027_daily_opportunity_top10
Revises: 0026_position_leg_quantities
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_daily_opportunity_top10"
down_revision = "0026_position_leg_quantities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_opportunity_top10",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trading_day", sa.String(10), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("candidate_source", sa.String(64), nullable=False, server_default=""),
        sa.Column("factor_evidence_json", sa.JSON(), nullable=True),
        sa.Column("frozen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("trading_day", "rank", name="uq_daily_top10_day_rank"),
        sa.UniqueConstraint("trading_day", "symbol", name="uq_daily_top10_day_symbol"),
    )
    op.create_index("ix_daily_top10_trading_day", "daily_opportunity_top10", ["trading_day"])


def downgrade() -> None:
    op.drop_index("ix_daily_top10_trading_day", table_name="daily_opportunity_top10")
    op.drop_table("daily_opportunity_top10")
