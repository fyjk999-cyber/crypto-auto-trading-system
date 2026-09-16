"""Autonomous per-horizon outcome maturations (derived, learning only).

Revision ID: 0033_outcome_maturations
Revises: 0032_opportunity_ledger
"""

import sqlalchemy as sa
from alembic import op

revision = "0033_outcome_maturations"
down_revision = "0032_opportunity_ledger"
branch_labels = None
depends_on = None

FLOAT_COLUMNS = (
    "entry_price",
    "target_price",
    "alignment_error_seconds",
    "long_gross_bps",
    "short_gross_bps",
    "all_in_cost_bps",
    "long_net_bps",
    "short_net_bps",
    "net_edge_bps",
    "future_high",
    "future_low",
    "mfe_bps",
    "mae_bps",
    "realized_volatility",
)


def upgrade() -> None:
    op.create_table(
        "opportunity_outcome_maturations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("observation_id", sa.String(64), nullable=False),
        sa.Column("trading_day", sa.String(10)),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("horizon", sa.String(8), nullable=False),
        sa.Column("outcome_version", sa.String(16), server_default="outcome-v1"),
        sa.Column("market_source", sa.String(24), server_default="OKX_PUBLIC_CANDLES"),
        sa.Column("direction_source", sa.String(24), server_default="NONE"),
        sa.Column("expected_direction", sa.String(8)),
        *[sa.Column(name, sa.Float()) for name in FLOAT_COLUMNS],
        sa.Column("alignment_ok", sa.Boolean(), server_default=sa.false()),
        sa.Column("requested_target_ts", sa.DateTime(timezone=True)),
        sa.Column("actual_target_ts", sa.DateTime(timezone=True)),
        sa.Column("path_start_ts", sa.DateTime(timezone=True)),
        sa.Column("path_end_ts", sa.DateTime(timezone=True)),
        sa.Column("label", sa.String(32)),
        sa.Column("cost_version", sa.String(16), server_default="all-in-v1"),
        sa.Column("authority", sa.String(24), server_default="LEARNING_ONLY"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "observation_id",
            "horizon",
            "outcome_version",
            name="uq_outcome_maturation_identity",
        ),
    )
    op.create_index(
        "ix_outcome_maturation_observation_id",
        "opportunity_outcome_maturations",
        ["observation_id"],
    )
    op.create_index(
        "ix_outcome_maturation_trading_day", "opportunity_outcome_maturations", ["trading_day"]
    )
    op.create_index("ix_outcome_maturation_symbol", "opportunity_outcome_maturations", ["symbol"])
    op.create_index("ix_outcome_maturation_horizon", "opportunity_outcome_maturations", ["horizon"])


def downgrade() -> None:
    for name in (
        "ix_outcome_maturation_horizon",
        "ix_outcome_maturation_symbol",
        "ix_outcome_maturation_trading_day",
        "ix_outcome_maturation_observation_id",
    ):
        op.drop_index(name, table_name="opportunity_outcome_maturations")
    op.drop_table("opportunity_outcome_maturations")
