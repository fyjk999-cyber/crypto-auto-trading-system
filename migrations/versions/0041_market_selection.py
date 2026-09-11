"""ChiefTrader market selection: durable record + decision lineage.

Adds ``market_selections`` (research-attention authority only) and the
``scan_id`` / ``selection_id`` lineage columns on ``llm_decisions`` so the
factual chain

    MarketObservationSnapshot -> MarketSelection -> ResearchTarget ->
    ToolSelection -> DynamicEvidencePackage -> LLMDecision -> TradePlan ->
    RiskDecision -> Order/Fill

is reconstructable. No directive/authority behaviour changes.

Revision ID: 0041_market_selection
Revises: 0040_runtime_settings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041_market_selection"
down_revision = "0040_runtime_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "market_selections" not in tables:
        op.create_table(
            "market_selections",
            sa.Column("selection_id", sa.String(64), primary_key=True),
            sa.Column("scan_id", sa.String(64), nullable=True),
            sa.Column("provider", sa.String(64), nullable=True),
            sa.Column("model", sa.String(128), nullable=True),
            sa.Column("prompt_version", sa.String(64), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("candidate_set_ref", sa.String(255), nullable=True),
            sa.Column("directory_query_refs_json", sa.JSON(), nullable=True),
            sa.Column("selected_symbols_json", sa.JSON(), nullable=True),
            sa.Column("selection_source", sa.String(40), nullable=True),
            sa.Column("selection_state", sa.String(24), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("error_code", sa.String(64), nullable=True),
            sa.Column("input_tokens", sa.Integer(), nullable=True),
            sa.Column("output_tokens", sa.Integer(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("snapshot_age_seconds", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_market_selections_scan_id", "market_selections", ["scan_id"])
        op.create_index("ix_market_selections_status", "market_selections", ["status"])

    if "llm_decisions" in tables:
        existing = {column["name"] for column in inspector.get_columns("llm_decisions")}
        if "scan_id" not in existing:
            op.add_column("llm_decisions", sa.Column("scan_id", sa.String(64), nullable=True))
        if "selection_id" not in existing:
            op.add_column(
                "llm_decisions", sa.Column("selection_id", sa.String(64), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "llm_decisions" in tables:
        existing = {column["name"] for column in inspector.get_columns("llm_decisions")}
        if "selection_id" in existing:
            op.drop_column("llm_decisions", "selection_id")
        if "scan_id" in existing:
            op.drop_column("llm_decisions", "scan_id")
    if "market_selections" in tables:
        op.drop_table("market_selections")
