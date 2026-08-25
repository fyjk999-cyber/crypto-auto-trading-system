"""add factor v9 prediction tables

Revision ID: 0012_factor_v9
Revises: 0011_factor_v7
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_factor_v9"
down_revision = "0011_factor_v7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regime_forecasts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("current_regime", sa.String(32), nullable=False),
        sa.Column("probabilities_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_regime_forecasts_symbol", "regime_forecasts", ["symbol"])
    op.create_table(
        "factor_forecasts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("factor_name", sa.String(32), nullable=False),
        sa.Column("current_health", sa.String(16), nullable=False),
        sa.Column("degrading_probability", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factor_forecasts_factor_name", "factor_forecasts", ["factor_name"])
    op.create_table(
        "confidence_forecasts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("research_id", sa.String(64), nullable=False),
        sa.Column("valid_probability", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_confidence_forecasts_research_id", "confidence_forecasts", ["research_id"])
    op.create_table(
        "prediction_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("prediction_json", sa.JSON(), nullable=True),
        sa.Column("actual", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("prediction_results")
    op.drop_index("ix_confidence_forecasts_research_id", table_name="confidence_forecasts")
    op.drop_table("confidence_forecasts")
    op.drop_index("ix_factor_forecasts_factor_name", table_name="factor_forecasts")
    op.drop_table("factor_forecasts")
    op.drop_index("ix_regime_forecasts_symbol", table_name="regime_forecasts")
    op.drop_table("regime_forecasts")
