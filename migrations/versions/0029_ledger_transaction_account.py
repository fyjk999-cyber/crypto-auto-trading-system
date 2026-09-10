"""formal account_id on ledger transactions

Revision ID: 0029_ledger_account
Revises: 0028_daily_review_claim
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_ledger_account"
down_revision = "0028_daily_review_claim"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ledger_transactions" not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_columns("ledger_transactions")}
    if "account_id" not in existing:
        op.add_column(
            "ledger_transactions",
            sa.Column("account_id", sa.String(64), nullable=True),
        )
    # Historical ownership is not provable from a singleton projection.
    # Leave account_id NULL and mark dependent valuations incomplete instead
    # of silently attributing old transactions to "default".


def downgrade() -> None:
    op.drop_column("ledger_transactions", "account_id")
