"""persist canonical llm fail-closed reason codes

Revision ID: 0019_llm_decision_reasons
Revises: 0018_trade_plan_contract
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_llm_decision_reasons"
down_revision = "0018_trade_plan_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_decisions", sa.Column("reason_codes_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_decisions", "reason_codes_json")
