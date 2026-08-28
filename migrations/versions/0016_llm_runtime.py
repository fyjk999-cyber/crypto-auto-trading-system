"""add shared LLM runtime configuration and usage tables

Revision ID: 0016_llm_runtime
Revises: 0015_hierarchical
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_llm_runtime"
down_revision = "0015_hierarchical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("provider_id", sa.String(64), primary_key=True),
        sa.Column("provider_type", sa.String(16), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("api_key_secret_ref", sa.String(160), nullable=False, unique=True),
        sa.Column("default_model", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "llm_routes",
        sa.Column("route_name", sa.String(64), primary_key=True),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_routes_provider_id", "llm_routes", ["provider_id"])
    op.create_table(
        "llm_usage",
        sa.Column("invocation_id", sa.String(64), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("brain", sa.String(16), nullable=False),
        sa.Column("route", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_classification", sa.String(40), nullable=True),
        sa.Column("correlation_id", sa.String(100), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_llm_usage_timestamp", "llm_usage", ["timestamp"])
    op.create_index("ix_llm_usage_brain", "llm_usage", ["brain"])
    op.create_index("ix_llm_usage_route", "llm_usage", ["route"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_route", table_name="llm_usage")
    op.drop_index("ix_llm_usage_brain", table_name="llm_usage")
    op.drop_index("ix_llm_usage_timestamp", table_name="llm_usage")
    op.drop_table("llm_usage")
    op.drop_index("ix_llm_routes_provider_id", table_name="llm_routes")
    op.drop_table("llm_routes")
    op.drop_table("llm_providers")
