"""funding coverage raw-history / boundary proof audit columns

Revision ID: 0034_funding_proof
Revises: 0033_valuation_truth
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_funding_proof"
down_revision = "0033_valuation_truth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "funding_coverage_windows" not in set(inspector.get_table_names()):
        return
    existing = {
        column["name"] for column in inspector.get_columns("funding_coverage_windows")
    }
    columns = {
        "fetched_count": sa.Column(
            "fetched_count", sa.Integer(), nullable=False, server_default="0"
        ),
        "window_event_count": sa.Column(
            "window_event_count", sa.Integer(), nullable=False, server_default="0"
        ),
        "boundary_proof": sa.Column(
            "boundary_proof", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    }
    for name, column in columns.items():
        if name not in existing:
            op.add_column("funding_coverage_windows", column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "funding_coverage_windows" not in set(inspector.get_table_names()):
        return
    existing = {
        column["name"] for column in inspector.get_columns("funding_coverage_windows")
    }
    for name in ("boundary_proof", "window_event_count", "fetched_count"):
        if name in existing:
            op.drop_column("funding_coverage_windows", name)
