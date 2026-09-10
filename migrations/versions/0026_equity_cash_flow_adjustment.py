"""cash-flow adjusted equity snapshots

Revision ID: 0026_equity_cash_flow
Revises: 0025_daily_review_durability
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_equity_cash_flow"
down_revision = "0025_daily_review_durability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "equity_snapshots" not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_columns("equity_snapshots")}
    columns = {
        "raw_equity": sa.Column("raw_equity", sa.String(80), nullable=False, server_default="0"),
        "external_cash_flow_adjustment": sa.Column(
            "external_cash_flow_adjustment", sa.String(80), nullable=False, server_default="0"
        ),
        "cash_flow_adjusted_equity": sa.Column(
            "cash_flow_adjusted_equity", sa.String(80), nullable=False, server_default="0"
        ),
        "peak_adjusted_equity": sa.Column(
            "peak_adjusted_equity", sa.String(80), nullable=False, server_default="0"
        ),
        "valuation_status": sa.Column(
            "valuation_status", sa.String(16), nullable=False, server_default="HEALTHY"
        ),
    }
    for name, column in columns.items():
        if name not in existing:
            op.add_column("equity_snapshots", column)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "equity_snapshots" not in set(inspector.get_table_names()):
        return
    for name in (
        "valuation_status",
        "peak_adjusted_equity",
        "cash_flow_adjusted_equity",
        "external_cash_flow_adjustment",
        "raw_equity",
    ):
        op.drop_column("equity_snapshots", name)
