"""add unique decision_id to trade_plans

Revision ID: 0027_trade_plan_decision_unique
Revises: 0026_trade_plans
"""
from alembic import op

revision = "0027_trade_plan_decision_unique"
down_revision = "0026_trade_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_trade_plans_decision_id_unique", "trade_plans", ["decision_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_trade_plans_decision_id_unique", table_name="trade_plans")
