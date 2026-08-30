"""durable trade plans for full-lifecycle AI

Revision ID: 0026_trade_plans
Revises: 0025_position_reviews
"""
import sqlalchemy as sa
from alembic import op

revision = "0026_trade_plans"
down_revision = "0025_position_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_plans",
        sa.Column("trade_plan_id", sa.String(64), primary_key=True),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("llm_invocation_id", sa.String(80), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("execution_symbol", sa.String(40), nullable=False),
        sa.Column("market_type", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("selected_strategy", sa.String(64), nullable=True),
        sa.Column("strategy_version", sa.String(32), nullable=True),
        sa.Column("market_regime", sa.String(32), nullable=True),
        sa.Column("entry_thesis", sa.String(500), nullable=False),
        sa.Column("supporting_evidence", sa.JSON(), nullable=True),
        sa.Column("contradicting_evidence", sa.JSON(), nullable=True),
        sa.Column("invalidation_conditions", sa.JSON(), nullable=True),
        sa.Column("target_conditions", sa.JSON(), nullable=True),
        sa.Column("expected_horizon_seconds", sa.Float(), nullable=True),
        sa.Column("max_holding_time_seconds", sa.Float(), nullable=True),
        sa.Column("risk_intent", sa.String(16), nullable=False),
        sa.Column("entry_price_reference", sa.String(80), nullable=True),
        sa.Column("factor_snapshot_id", sa.String(64), nullable=True),
        sa.Column("tool_trace_id", sa.String(64), nullable=True),
        sa.Column("memory_refs", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_trade_plans_decision_id", "trade_plans", ["decision_id"])
    op.create_index("ix_trade_plans_symbol", "trade_plans", ["symbol"])
    op.create_index("ix_trade_plans_status", "trade_plans", ["status"])


def downgrade() -> None:
    op.drop_index("ix_trade_plans_status", table_name="trade_plans")
    op.drop_index("ix_trade_plans_symbol", table_name="trade_plans")
    op.drop_index("ix_trade_plans_decision_id", table_name="trade_plans")
    op.drop_table("trade_plans")
