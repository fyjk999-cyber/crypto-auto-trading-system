"""Low-Risk V2 TradePlan contract + versioning (Phase 4B/4C).

Additive, nullable columns so every existing plan remains readable and a new
LLM entry can carry a versioned contract: Base Exit, exit approach, adverse
trigger, thesis invalidation, reassessment rules, NEXT_REASSESSMENT, strategy
and all-in economics estimates.

No existing column is rewritten; `plan_version` defaults to 1 for legacy plans.

Revision ID: 0024_trade_plan_v2_contract
Revises: 0023_opportunity_lineage
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_trade_plan_v2_contract"
down_revision = "0023_opportunity_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trade_plans",
        sa.Column("plan_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "trade_plans", sa.Column("strategy", sa.String(64), nullable=False, server_default="")
    )
    op.add_column(
        "trade_plans", sa.Column("based_on_state_version", sa.String(64), nullable=True)
    )
    op.add_column("trade_plans", sa.Column("base_exit_json", sa.JSON(), nullable=True))
    op.add_column(
        "trade_plans",
        sa.Column("exit_approach", sa.String(255), nullable=False, server_default=""),
    )
    op.add_column("trade_plans", sa.Column("adverse_trigger_json", sa.JSON(), nullable=True))
    op.add_column(
        "trade_plans",
        sa.Column("thesis_invalidation", sa.String(1000), nullable=False, server_default=""),
    )
    op.add_column("trade_plans", sa.Column("reassessment_rules_json", sa.JSON(), nullable=True))
    op.add_column("trade_plans", sa.Column("next_reassessment_json", sa.JSON(), nullable=True))
    op.add_column("trade_plans", sa.Column("expected_edge_bps", sa.Float(), nullable=True))
    op.add_column("trade_plans", sa.Column("expected_cost_bps", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("trade_plans", "expected_cost_bps")
    op.drop_column("trade_plans", "expected_edge_bps")
    op.drop_column("trade_plans", "next_reassessment_json")
    op.drop_column("trade_plans", "reassessment_rules_json")
    op.drop_column("trade_plans", "thesis_invalidation")
    op.drop_column("trade_plans", "adverse_trigger_json")
    op.drop_column("trade_plans", "exit_approach")
    op.drop_column("trade_plans", "base_exit_json")
    op.drop_column("trade_plans", "based_on_state_version")
    op.drop_column("trade_plans", "strategy")
    op.drop_column("trade_plans", "plan_version")
