"""daily review claim owner + deadline fencing

Revision ID: 0035_review_claim
Revises: 0034_funding_proof
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_review_claim"
down_revision = "0034_funding_proof"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "daily_review_runs" not in set(inspector.get_table_names()):
        return
    existing = {
        column["name"] for column in inspector.get_columns("daily_review_runs")
    }
    if "owner" not in existing:
        op.add_column(
            "daily_review_runs", sa.Column("owner", sa.String(64), nullable=True)
        )
    if "claim_deadline_at" not in existing:
        op.add_column(
            "daily_review_runs",
            sa.Column("claim_deadline_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "daily_review_runs" not in set(inspector.get_table_names()):
        return
    existing = {
        column["name"] for column in inspector.get_columns("daily_review_runs")
    }
    if "claim_deadline_at" in existing:
        op.drop_column("daily_review_runs", "claim_deadline_at")
    if "owner" in existing:
        op.drop_column("daily_review_runs", "owner")
