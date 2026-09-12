"""Isolated shadow learning tables (counterfactual sidecar).

Adds three tables in their own namespace:

    shadow_candidates, shadow_episodes, shadow_evaluation_runs

These describe HYPOTHETICAL outcomes for decisions the ChiefTrader already
committed. They are deliberately separate from ``orders``, ``fills``,
``positions_projection`` and ``trade_episodes`` so shadow data can never be
mistaken for real activity, and so every real consumer keeps its exact previous
semantics.

Nothing in this migration touches an existing table.

Revision ID: 0043_shadow_learning
Revises: 0042_selection_exploration
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043_shadow_learning"
down_revision = "0042_selection_exploration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "shadow_candidates" not in tables:
        op.create_table(
            "shadow_candidates",
            sa.Column("candidate_id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("symbol", sa.String(64), nullable=False),
            sa.Column("direction_hypothesis", sa.String(8), nullable=False),
            sa.Column("reference_price", sa.String(80), nullable=False),
            sa.Column("source_candidate_id", sa.String(64), nullable=True),
            sa.Column("source_decision_id", sa.String(64), nullable=False),
            sa.Column("strategy_id", sa.String(64), nullable=False),
            sa.Column("strategy_version", sa.String(64), nullable=False),
            sa.Column("market_snapshot_id", sa.String(64), nullable=True),
            sa.Column("factor_snapshot_id", sa.String(64), nullable=True),
            sa.Column("market_regime", sa.String(64), nullable=False),
            sa.Column("chieftrader_action", sa.String(32), nullable=False),
            sa.Column("chieftrader_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("hypothetical_entry_rule", sa.String(64), nullable=False),
            sa.Column("hypothetical_exit_rule", sa.String(64), nullable=False),
            sa.Column("stop_rule", sa.String(80), nullable=True),
            sa.Column("take_profit_rule", sa.String(80), nullable=True),
            sa.Column("max_hold_seconds", sa.Integer(), nullable=False),
            sa.Column("evaluation_horizons_json", sa.JSON(), nullable=False),
            sa.Column("rules_fingerprint", sa.String(64), nullable=False),
            sa.Column("dedup_key", sa.String(255), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
            sa.Column("observation_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("dedup_key", name="uq_shadow_candidates_dedup_key"),
        )
        op.create_index(
            "ix_shadow_candidates_symbol", "shadow_candidates", ["symbol"]
        )
        op.create_index(
            "ix_shadow_candidates_status", "shadow_candidates", ["status"]
        )
        op.create_index(
            "ix_shadow_candidates_source_decision",
            "shadow_candidates",
            ["source_decision_id"],
        )

    if "shadow_episodes" not in tables:
        op.create_table(
            "shadow_episodes",
            sa.Column("shadow_episode_id", sa.String(64), primary_key=True),
            sa.Column("shadow_candidate_id", sa.String(64), nullable=False),
            sa.Column("source_decision_id", sa.String(64), nullable=False),
            sa.Column("symbol", sa.String(64), nullable=False),
            sa.Column("direction", sa.String(8), nullable=False),
            sa.Column("strategy_id", sa.String(64), nullable=False),
            sa.Column("strategy_version", sa.String(64), nullable=False),
            sa.Column("regime", sa.String(64), nullable=False),
            sa.Column("hypothetical_entry_at", sa.DateTime(), nullable=False),
            sa.Column("hypothetical_entry_price", sa.String(80), nullable=False),
            sa.Column("hypothetical_exit_at", sa.DateTime(), nullable=True),
            sa.Column("hypothetical_exit_price", sa.String(80), nullable=True),
            sa.Column("normalized_notional", sa.String(80), nullable=False),
            sa.Column("gross_return", sa.String(80), nullable=True),
            sa.Column("fee_adjusted_return", sa.String(80), nullable=True),
            sa.Column("mfe", sa.String(80), nullable=True),
            sa.Column("mae", sa.String(80), nullable=True),
            sa.Column("holding_seconds", sa.Integer(), nullable=True),
            sa.Column("exit_reason", sa.String(64), nullable=True),
            sa.Column("outcome_class", sa.String(32), nullable=False),
            sa.Column("factual", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "evidence_type",
                sa.String(32),
                nullable=False,
                server_default="SHADOW_EPISODE",
            ),
            sa.Column("evaluator_version", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "shadow_candidate_id", name="uq_shadow_episodes_candidate"
            ),
        )
        op.create_index("ix_shadow_episodes_symbol", "shadow_episodes", ["symbol"])

    if "shadow_evaluation_runs" not in tables:
        op.create_table(
            "shadow_evaluation_runs",
            sa.Column("run_id", sa.String(64), primary_key=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("considered", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("evaluated", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matured", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("dropped", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_summary", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for name in ("shadow_episodes", "shadow_candidates", "shadow_evaluation_runs"):
        if name in tables:
            op.drop_table(name)
