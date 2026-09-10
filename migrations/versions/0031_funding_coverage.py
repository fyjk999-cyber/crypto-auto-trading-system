"""durable funding coverage windows

Revision ID: 0031_funding_coverage
Revises: 0030_valuation_batches
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_funding_coverage"
down_revision = "0030_valuation_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "funding_coverage_windows" in set(inspector.get_table_names()):
        return
    op.create_table(
        "funding_coverage_windows",
        sa.Column("coverage_id", sa.String(64), primary_key=True),
        sa.Column("instrument_id", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(64), nullable=False, server_default="OKX_PUBLIC"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pagination_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("event_manifest_hash", sa.String(128), nullable=True),
        sa.Column("gaps_json", sa.JSON(), nullable=True),
        sa.Column("rule_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("coverage_status", sa.String(16), nullable=False, server_default="UNKNOWN"),
    )


def downgrade() -> None:
    op.drop_table("funding_coverage_windows")
