"""add AI memory, shadow campaign, and capital allocation tables

Revision ID: 0003_ai_memory
Revises: 0002_add_fence_generation
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_ai_memory"
down_revision = "0002addfence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_strategy_cards",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_name", sa.String(64), nullable=False),
        sa.Column("strategy_family", sa.String(64), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("ideal_market_regime", sa.String(32), nullable=False),
        sa.Column("bad_market_regime", sa.String(32), nullable=False),
        sa.Column("entry_logic", sa.String(1000), nullable=False),
        sa.Column("exit_logic", sa.String(1000), nullable=False),
        sa.Column("failure_modes", sa.String(1000), nullable=False),
        sa.Column("required_tools", sa.String(500), nullable=False),
        sa.Column("historical_examples", sa.String(1000), nullable=False),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ai_trade_episodes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("episode_id", sa.String(64), nullable=False, unique=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("market_regime", sa.String(16), nullable=False),
        sa.Column("market_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("quant_evidence_json", sa.JSON(), nullable=True),
        sa.Column("strategy_selected", sa.String(200), nullable=False),
        sa.Column("llm_reasoning", sa.String(2000), nullable=False),
        sa.Column("entry_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("exit_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("position_size", sa.Numeric(38, 18), nullable=False),
        sa.Column("leverage", sa.Numeric(38, 18), nullable=False),
        sa.Column("holding_time_seconds", sa.Float(), nullable=False),
        sa.Column("pnl", sa.Numeric(38, 18), nullable=False),
        sa.Column("mfe", sa.Numeric(38, 18), nullable=False),
        sa.Column("mae", sa.Numeric(38, 18), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("review_status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_trade_episodes_symbol", "ai_trade_episodes", ["symbol"])
    op.create_table(
        "ai_trade_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("episode_id", sa.String(64), nullable=False, unique=True),
        sa.Column("success_factors_json", sa.JSON(), nullable=True),
        sa.Column("failure_factors_json", sa.JSON(), nullable=True),
        sa.Column("mistakes_json", sa.JSON(), nullable=True),
        sa.Column("lessons_json", sa.JSON(), nullable=True),
        sa.Column("future_rules_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ai_market_patterns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pattern_id", sa.String(64), nullable=False, unique=True),
        sa.Column("regime", sa.String(16), nullable=False),
        sa.Column("features_json", sa.JSON(), nullable=True),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("win_rate", sa.Numeric(38, 18), nullable=False),
        sa.Column("profit_factor", sa.Numeric(38, 18), nullable=False),
        sa.Column("success_drivers_json", sa.JSON(), nullable=True),
        sa.Column("failure_drivers_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=False),
        sa.Column("embedding_json", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ai_coin_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False, unique=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("profile_summary", sa.String(200), nullable=False),
        sa.Column("behavior_tags_json", sa.JSON(), nullable=True),
        sa.Column("best_setups_json", sa.JSON(), nullable=True),
        sa.Column("worst_setups_json", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ai_compressed_experience",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.String(2000), nullable=False),
        sa.Column("source_episode_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "shadow_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.String(64), nullable=False, unique=True),
        sa.Column("start_time", sa.String(64), nullable=True),
        sa.Column("last_observation_time", sa.String(64), nullable=True),
        sa.Column("elapsed_real_calendar_days", sa.Float(), nullable=False),
        sa.Column("valid_observation_days", sa.Integer(), nullable=False),
        sa.Column("decision_count", sa.Integer(), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("no_trade_count", sa.Integer(), nullable=False),
        sa.Column("symbol_coverage_json", sa.JSON(), nullable=True),
        sa.Column("regime_coverage_json", sa.JSON(), nullable=True),
        sa.Column("downtime_hours", sa.Float(), nullable=False),
        sa.Column("provider_failures", sa.Integer(), nullable=False),
        sa.Column("market_data_failures", sa.Integer(), nullable=False),
        sa.Column("critical_incidents", sa.Integer(), nullable=False),
        sa.Column("data_quality_score", sa.Float(), nullable=False),
        sa.Column("campaign_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "capital_allocations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("allocation_id", sa.String(64), nullable=False, unique=True),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("requested_capital_fraction", sa.Numeric(38, 18), nullable=False),
        sa.Column("recommended_capital_fraction", sa.Numeric(38, 18), nullable=False),
        sa.Column("recommended_notional", sa.Numeric(38, 18), nullable=False),
        sa.Column("recommended_risk_budget", sa.Numeric(38, 18), nullable=False),
        sa.Column("max_allowed_fraction", sa.Numeric(38, 18), nullable=False),
        sa.Column("allocation_confidence", sa.Numeric(38, 18), nullable=False),
        sa.Column("reason_codes_json", sa.JSON(), nullable=True),
        sa.Column("policy_version", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_capital_allocations_symbol", "capital_allocations", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_capital_allocations_symbol", table_name="capital_allocations")
    op.drop_table("capital_allocations")
    op.drop_table("shadow_campaigns")
    op.drop_table("ai_compressed_experience")
    op.drop_table("ai_coin_profiles")
    op.drop_table("ai_market_patterns")
    op.drop_table("ai_trade_reviews")
    op.drop_index("ix_ai_trade_episodes_symbol", table_name="ai_trade_episodes")
    op.drop_table("ai_trade_episodes")
    op.drop_table("llm_strategy_cards")
