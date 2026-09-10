"""cumulative external cash flow on equity snapshots

Revision ID: 0027_cumulative_cash_flow
Revises: 0026_equity_cash_flow
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_cumulative_cash_flow"
down_revision = "0026_equity_cash_flow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "equity_snapshots" not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_columns("equity_snapshots")}
    for name in ("period_external_cash_flow", "cumulative_external_cash_flow"):
        if name not in existing:
            op.add_column(
                "equity_snapshots",
                sa.Column(name, sa.String(80), nullable=False, server_default="0"),
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "equity_snapshots" not in set(inspector.get_table_names()):
        return
    op.drop_column("equity_snapshots", "cumulative_external_cash_flow")
    op.drop_column("equity_snapshots", "period_external_cash_flow")
