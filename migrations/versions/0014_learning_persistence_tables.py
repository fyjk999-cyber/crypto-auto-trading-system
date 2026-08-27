"""add learning persistence tables

Revision ID: 0014_learning
Revises: 0013_factor_v10
Create Date: 2026-08-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_learning"
down_revision = "0013_factor_v10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("decision_id", sa.String(64), nullable=False, unique=True),
        sa.Column("timestamp_utc", sa.String(40), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("strategy_id", sa.String(32), nullable=False),
        sa.Column("strategy_version", sa.String(16), nullable=False),
        sa.Column("model_version", sa.String(16), nullable=False),
        sa.Column("prompt_version", sa.String(16), nullable=False),
        sa.Column("factor_snapshot_id", sa.String(64), nullable=False),
        sa.Column("factor_set_version", sa.String(32), nullable=False),
        sa.Column("factor_profile", sa.String(32), nullable=False),
        sa.Column("market_data_reference", sa.String(64), nullable=False),
        sa.Column("analysis_evidence_json", sa.JSON(), nullable=True),
        sa.Column("decision_json", sa.JSON(), nullable=True),
        sa.Column("risk_decision_json", sa.JSON(), nullable=True),
        sa.Column("execution_intent_reference", sa.String(64), nullable=False),
        sa.Column("created_at_utc", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_decision_evidence_symbol", "decision_evidence", ["symbol"])
    op.create_table(
        "daily_review_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("review_id", sa.String(64), nullable=False, unique=True),
        sa.Column("review_type", sa.String(16), nullable=False),
        sa.Column("period_id", sa.String(16), nullable=False),
        sa.Column("starts_at", sa.String(40), nullable=False),
        sa.Column("ends_at", sa.String(40), nullable=False),
        sa.Column("triggered_at", sa.String(40), nullable=False),
        sa.Column("decision_count", sa.Integer(), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("data_quality", sa.String(16), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_daily_review_results_period_id", "daily_review_results", ["period_id"])
    op.create_table(
        "learning_pattern_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pattern_id", sa.String(64), nullable=False, unique=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("pattern_type", sa.String(64), nullable=False),
        sa.Column("conditions_json", sa.JSON(), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("decision_ids_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "learning_lessons",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lesson_id", sa.String(64), nullable=False, unique=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("canonical_statement", sa.String(500), nullable=False),
        sa.Column("conditions_json", sa.JSON(), nullable=True),
        sa.Column("recommended_action", sa.String(200), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("supporting_decisions_json", sa.JSON(), nullable=True),
        sa.Column("contradictions_json", sa.JSON(), nullable=True),
        sa.Column("first_seen", sa.String(40), nullable=False),
        sa.Column("last_seen", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_review_ids_json", sa.JSON(), nullable=True),
        sa.Column("source_pattern_ids_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "learning_review_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("review_key", sa.String(64), nullable=False, unique=True),
        sa.Column("review_id", sa.String(64), nullable=False),
        sa.Column("period_type", sa.String(16), nullable=False),
        sa.Column("period_id", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("completed_at", sa.String(40), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("learning_review_jobs")
    op.drop_table("learning_lessons")
    op.drop_table("learning_pattern_candidates")
    op.drop_index("ix_daily_review_results_period_id", table_name="daily_review_results")
    op.drop_table("daily_review_results")
    op.drop_index("ix_decision_evidence_symbol", table_name="decision_evidence")
    op.drop_table("decision_evidence")
