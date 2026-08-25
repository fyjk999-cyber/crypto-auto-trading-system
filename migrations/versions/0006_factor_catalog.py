"""add factor catalog table

Revision ID: 0006_factor_catalog
Revises: 0005_factor_eval
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_factor_catalog"
down_revision = "0005_factor_eval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "factor_catalog",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("factor_id", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("formula", sa.String(200), nullable=False),
        sa.Column("data_source", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("factor_catalog")
