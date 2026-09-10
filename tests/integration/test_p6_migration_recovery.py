"""P6: migrated databases never promote unprovable ownership to known."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from crypto_trader.ledger.service import LedgerService
from crypto_trader.persistence.database import Database, create_sync_engine

PREVIOUS = "0031_funding_coverage"
HEAD = "0034_funding_proof"
START = datetime(2026, 9, 10, 0, tzinfo=UTC)
END = datetime(2026, 9, 10, 8, tzinfo=UTC)


def _config(database_path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def _insert_guessed_history(database_path) -> None:
    """Simulate the old broken 0029 backfilling account_id='default'."""
    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO ledger_transactions "
                "(transaction_id, account_id, entry_type, created_at) "
                "VALUES ('legacy_guessed', 'default', 'FUNDING_RECEIPT', :created_at)"
            ),
            {"created_at": "2026-09-10 04:00:00"},
        )
        conn.execute(
            sa.text(
                "INSERT INTO ledger_entries "
                "(entry_id, transaction_id, seq, entry_type, account, direction, "
                "amount, currency, created_at) "
                "VALUES ('legacy_entry', 'legacy_guessed', 1, 'FUNDING_RECEIPT', "
                "'FUNDING_RECEIPT', 'CREDIT', '5', 'USDT', :created_at)"
            ),
            {"created_at": "2026-09-10 04:00:00"},
        )


async def test_backfilled_history_remains_accounting_incomplete(tmp_path):
    database_path = tmp_path / "p6.db"
    config = _config(database_path)
    command.upgrade(config, PREVIOUS)
    _insert_guessed_history(database_path)
    command.upgrade(config, HEAD)

    database = Database(f"sqlite+aiosqlite:///{database_path}")
    try:
        ledger = LedgerService(database.session_factory)
        provenance = await ledger.net_pnl_provenance_since(
            START,
            account_id="default",
            currency="USDT",
            instrument_ids=[],
            end=END,
        )
        assert provenance.complete is False
        assert provenance.funding_status == "ACCOUNTING_INCOMPLETE"
        assert provenance.funding_amount is None
        assert "UNATTRIBUTED_LEDGER_OWNERSHIP" in provenance.unknown_reasons
        # The old guessed account value is retained for audit but never counted.
        assert provenance.known_funding_subtotal is None
    finally:
        await database.close()

    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT account_id, ownership_status FROM ledger_transactions "
                "WHERE transaction_id = 'legacy_guessed'"
            )
        ).one()
    assert row[0] == "default"
    assert row[1] == "UNKNOWN"
