"""Low-Risk V2 position legs (Phase 4D).

Adds the `position_legs` table: one row per factual leg (ENTRY/ADD/HEDGE/REVERSE)
carrying the independence contract (strategy, thesis, Base Exit, invalidation,
model-family evidence) and lineage (trade_plan_id, decision_id, state_version).

Additive only: no existing table/column is modified.

Revision ID: 0025_position_legs
Revises: 0024_trade_plan_v2_contract
"""

import sqlalchemy as sa
from alembic import op

revision = "0025_position_legs"
down_revision = "0024_trade_plan_v2_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_legs",
        sa.Column("leg_id", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="ENTRY"),
        sa.Column("strategy", sa.String(64), nullable=False, server_default=""),
        sa.Column("thesis", sa.String(2000), nullable=False, server_default=""),
        sa.Column("base_exit_json", sa.JSON(), nullable=True),
        sa.Column("invalidation", sa.String(1000), nullable=False, server_default=""),
        sa.Column("evidence_families_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=False, server_default=""),
        sa.Column("reverse_of", sa.String(64), nullable=True),
        sa.Column("trade_plan_id", sa.String(64), nullable=True),
        sa.Column("decision_id", sa.String(64), nullable=True),
        sa.Column("state_version", sa.String(128), nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("leg_id", name="uq_position_legs_leg_id"),
    )
    op.create_index("ix_position_legs_symbol", "position_legs", ["symbol"])
    op.create_index("ix_position_legs_trade_plan_id", "position_legs", ["trade_plan_id"])


def downgrade() -> None:
    op.drop_index("ix_position_legs_trade_plan_id", table_name="position_legs")
    op.drop_index("ix_position_legs_symbol", table_name="position_legs")
    op.drop_table("position_legs")
