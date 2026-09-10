"""durable factual equity snapshots for canonical drawdown

Revision ID: 0024_equity_snapshots
Revises: 0023_opportunity_lineage
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_equity_snapshots"
down_revision = "0023_opportunity_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equity_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("current_equity", sa.String(80), nullable=False),
        sa.Column("peak_equity", sa.String(80), nullable=False),
        sa.Column("drawdown", sa.String(80), nullable=False),
        sa.Column(
            "valuation_source",
            sa.String(64),
            nullable=False,
            server_default="LEDGER_PROJECTION",
        ),
        sa.Column("valuation_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("equity_snapshots")
