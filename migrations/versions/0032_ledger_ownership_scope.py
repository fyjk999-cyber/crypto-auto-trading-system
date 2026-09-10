"""ledger transaction ownership + instrument scope

Revision ID: 0032_ledger_ownership
Revises: 0031_funding_coverage
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_ledger_ownership"
down_revision = "0031_funding_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ledger_transactions" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("ledger_transactions")}
    indexes = {index["name"] for index in inspector.get_indexes("ledger_transactions")}
    if "instrument_id" not in columns:
        op.add_column(
            "ledger_transactions",
            sa.Column("instrument_id", sa.String(64), nullable=True),
        )
    if "ix_ledger_transactions_instrument_id" not in indexes:
        op.create_index(
            "ix_ledger_transactions_instrument_id",
            "ledger_transactions",
            ["instrument_id"],
        )

    if "ownership_status" not in columns:
        op.add_column(
            "ledger_transactions",
            sa.Column(
                "ownership_status",
                sa.String(16),
                nullable=False,
                server_default="UNKNOWN",
            ),
        )
    if "ix_ledger_transactions_ownership_status" not in indexes:
        op.create_index(
            "ix_ledger_transactions_ownership_status",
            "ledger_transactions",
            ["ownership_status"],
        )

    # Corrective step for databases that already ran the pre-correction 0029:
    # that revision backfilled account_id='default' for every historical row
    # without proof. The corrected 0029 leaves historical account_id NULL, but
    # both cases are indistinguishable after the fact. Every row that predates
    # this migration is therefore marked UNKNOWN unless it was written by the
    # canonical writer after ownership tracking existed. account_id values are
    # preserved for audit, but scoped accounting queries require
    # ownership_status='VERIFIED', so old guessed rows can never be counted.
    op.execute(
        sa.text(
            "UPDATE ledger_transactions "
            "SET ownership_status = 'UNKNOWN' "
            "WHERE ownership_status IS NULL OR ownership_status = ''"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ledger_transactions" not in set(inspector.get_table_names()):
        return
    indexes = {index["name"] for index in inspector.get_indexes("ledger_transactions")}
    columns = {column["name"] for column in inspector.get_columns("ledger_transactions")}
    if "ix_ledger_transactions_ownership_status" in indexes:
        op.drop_index(
            "ix_ledger_transactions_ownership_status", table_name="ledger_transactions"
        )
    if "ownership_status" in columns:
        op.drop_column("ledger_transactions", "ownership_status")
    if "ix_ledger_transactions_instrument_id" in indexes:
        op.drop_index(
            "ix_ledger_transactions_instrument_id", table_name="ledger_transactions"
        )
    if "instrument_id" in columns:
        op.drop_column("ledger_transactions", "instrument_id")
