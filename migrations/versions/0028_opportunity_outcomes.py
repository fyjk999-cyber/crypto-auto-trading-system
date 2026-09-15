"""Growth V2 persisted opportunity outcomes (Phase 5).

Adds `opportunity_outcomes`: per frozen opportunity/horizon outcome labels
(TRADED_CORRECT/TRADED_WRONG/NOT_TRADED_*), all-in-net returns and MFE/MAE.

Revision ID: 0028_opportunity_outcomes
Revises: 0027_daily_opportunity_top10
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_opportunity_outcomes"
down_revision = "0027_daily_opportunity_top10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opportunity_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trading_day", sa.String(10), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("horizon", sa.String(8), nullable=False),
        sa.Column("expected_direction", sa.String(8), nullable=False),
        sa.Column("traded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("return_bps", sa.Float(), nullable=False, server_default="0"),
        sa.Column("net_return_bps", sa.Float(), nullable=False, server_default="0"),
        sa.Column("mfe_bps", sa.Float(), nullable=False, server_default="0"),
        sa.Column("mae_bps", sa.Float(), nullable=False, server_default="0"),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("authority", sa.String(32), nullable=False, server_default="LEARNING_ONLY"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "trading_day", "symbol", "horizon", name="uq_opportunity_outcomes_day_symbol_horizon"
        ),
    )
    op.create_index("ix_opportunity_outcomes_trading_day", "opportunity_outcomes", ["trading_day"])


def downgrade() -> None:
    op.drop_index("ix_opportunity_outcomes_trading_day", table_name="opportunity_outcomes")
    op.drop_table("opportunity_outcomes")
