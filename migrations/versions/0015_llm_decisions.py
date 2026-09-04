"""add canonical durable llm decisions

Revision ID: 0015_llm_decisions
Revises: 0014_trade_plans
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from crypto_trader.persistence.models import ExactDecimal

revision = "0015_llm_decisions"
down_revision = "0014_trade_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_decisions",
        sa.Column("decision_id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("position_state", sa.String(16), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("model_provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("market_regime", sa.String(64), nullable=False),
        sa.Column("thesis", sa.String(2000), nullable=False),
        sa.Column("supporting_evidence_json", sa.JSON(), nullable=True),
        sa.Column("contradicting_evidence_json", sa.JSON(), nullable=True),
        sa.Column("tool_refs_json", sa.JSON(), nullable=True),
        sa.Column("memory_refs_json", sa.JSON(), nullable=True),
        sa.Column("research_refs_json", sa.JSON(), nullable=True),
        sa.Column("episode_refs_json", sa.JSON(), nullable=True),
        sa.Column("requested_exposure", ExactDecimal(), nullable=True),
        sa.Column("requested_quantity", ExactDecimal(), nullable=True),
        sa.Column("requested_leverage", ExactDecimal(), nullable=True),
        sa.Column("parent_decision_id", sa.String(64), nullable=True),
        sa.Column("trade_plan_id", sa.String(64), nullable=True),
        sa.Column("position_quantity_before", ExactDecimal(), nullable=True),
        sa.Column("entry_price", ExactDecimal(), nullable=True),
        sa.Column("mark_price", ExactDecimal(), nullable=True),
        sa.Column("unrealized_pnl", ExactDecimal(), nullable=True),
        sa.Column("time_in_trade_seconds", sa.Float(), nullable=True),
        sa.Column("original_trade_plan_id", sa.String(64), nullable=True),
        sa.Column("original_entry_decision_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "run_id",
        "symbol",
        "action",
        "parent_decision_id",
        "trade_plan_id",
        "original_trade_plan_id",
        "original_entry_decision_id",
    ):
        op.create_index(f"ix_llm_decisions_{column}", "llm_decisions", [column])


def downgrade() -> None:
    op.drop_table("llm_decisions")
