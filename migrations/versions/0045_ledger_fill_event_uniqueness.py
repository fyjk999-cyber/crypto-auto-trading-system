"""one ledger transaction per fill / per event

``LedgerService.record`` already skips a fill_id it can see, but that check runs
in a SEPARATE session, so two concurrent writers can both observe "absent" and
both insert. Two settlement passes racing on one fill therefore produced TWO
TRADE transactions for that fill, duplicating the economic effect - measured, not
theorised: the engine-level concurrent apply_fill test failed with
MultipleResultsFound because ledger_transaction_for_fill found two rows.

A database-level unique index is the only guard that actually holds under
concurrency; the application check remains as a cheap fast path.

Nullable columns are used deliberately: NULL means "no identity" and SQLite
permits many NULLs, so rows that legitimately carry no fill_id/event_id are
unaffected. Empty strings are normalised to NULL in the service layer, because ""
is a value and several of them would collide.

Revision ID: 0045_ledger_fill_event_uniqueness
Revises: 0044_fill_settlements
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_ledger_fill_event_uniqueness"
down_revision = "0044_fill_settlements"
branch_labels = None
depends_on = None


def _assert_no_duplicates(column: str) -> None:
    """Refuse to create a unique index over data that already violates it.

    Silently dropping rows would destroy factual ledger history, and creating the
    index anyway would abort with a less informative error - so this reports the
    collisions and stops.
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            f"SELECT {column}, COUNT(*) AS n FROM ledger_transactions "
            f"WHERE {column} IS NOT NULL GROUP BY {column} HAVING COUNT(*) > 1 "
            "LIMIT 5"
        )
    ).fetchall()
    if rows:
        detail = ", ".join(f"{row[0]}x{row[1]}" for row in rows)
        raise RuntimeError(
            f"ledger_transactions.{column} already has duplicates ({detail}); "
            "resolve the accounting collision before applying this migration"
        )


def upgrade() -> None:
    # Normalise legacy empty strings so the unique index is meaningful.
    op.execute("UPDATE ledger_transactions SET fill_id = NULL WHERE fill_id = ''")
    op.execute("UPDATE ledger_transactions SET event_id = NULL WHERE event_id = ''")
    for column in ("fill_id", "event_id"):
        _assert_no_duplicates(column)
    op.create_index(
        "uq_ledger_transactions_fill_id",
        "ledger_transactions",
        ["fill_id"],
        unique=True,
    )
    op.create_index(
        "uq_ledger_transactions_event_id",
        "ledger_transactions",
        ["event_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_ledger_transactions_event_id", table_name="ledger_transactions")
    op.drop_index("uq_ledger_transactions_fill_id", table_name="ledger_transactions")
