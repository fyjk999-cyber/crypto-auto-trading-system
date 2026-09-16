"""Persistent Growth memory-speed records.

Revision ID: 0034_growth_memory_speeds
Revises: 0033_outcome_maturations
"""

import sqlalchemy as sa
from alembic import op

revision = "0034_growth_memory_speeds"
down_revision = "0033_outcome_maturations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "growth_memory_speeds",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("signature", sa.String(256), server_default=""),
        sa.Column("speed", sa.String(32), server_default="FAST_EXPERIENCE"),
        sa.Column("observations", sa.Integer(), server_default="0"),
        sa.Column("wins", sa.Integer(), server_default="0"),
        sa.Column("net_bps_total", sa.Float(), server_default="0"),
        sa.Column("regimes_json", sa.JSON()),
        sa.Column("demotions", sa.Integer(), server_default="0"),
        sa.Column("post_cost_expectancy_bps", sa.Float()),
        sa.Column("chronological_stable", sa.Boolean(), server_default=sa.true()),
        sa.Column("unresolved_contradictions", sa.Integer(), server_default="0"),
        sa.Column("policy_version", sa.String(32), server_default="memory-policy-v2"),
        sa.Column("can_modify_core", sa.Boolean(), server_default=sa.false()),
        sa.Column("authority", sa.String(24), server_default="LEARNING_ONLY"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("key", name="uq_growth_memory_speeds_key"),
    )
    op.create_index("ix_growth_memory_speeds_key", "growth_memory_speeds", ["key"])


def downgrade() -> None:
    op.drop_index("ix_growth_memory_speeds_key", table_name="growth_memory_speeds")
    op.drop_table("growth_memory_speeds")
