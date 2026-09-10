"""durable atomic review claim token

Revision ID: 0028_daily_review_claim
Revises: 0027_cumulative_cash_flow
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_daily_review_claim"
down_revision = "0027_cumulative_cash_flow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "daily_review_runs" not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_columns("daily_review_runs")}
    if "claim_token" not in existing:
        op.add_column(
            "daily_review_runs",
            sa.Column("claim_token", sa.String(64), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("daily_review_runs", "claim_token")
