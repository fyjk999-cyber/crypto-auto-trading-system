"""P0/P6 migration acceptance for ledger ownership correction."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from crypto_trader.persistence.database import create_sync_engine

HEAD = "0032_ledger_ownership"
PREVIOUS = "0031_funding_coverage"
CREATED_AT = datetime(2026, 9, 10, 4, tzinfo=UTC).isoformat(sep=" ")


def _config(database_path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def _insert_ledger_transaction(
    database_path, *, transaction_id: str, account_id, created_at=CREATED_AT
):
    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO ledger_transactions "
                "(transaction_id, account_id, entry_type, created_at) "
                "VALUES (:transaction_id, :account_id, 'FUNDING_RECEIPT', :created_at)"
            ),
            {
                "transaction_id": transaction_id,
                "account_id": account_id,
                "created_at": created_at,
            },
        )


def _rows(database_path):
    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.connect() as conn:
        return (
            conn.execute(
                sa.text(
                    "SELECT transaction_id, account_id, instrument_id, ownership_status "
                    "FROM ledger_transactions ORDER BY transaction_id"
                )
            )
            .mappings()
            .all()
        )


def _columns(database_path):
    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.connect() as conn:
        return {column["name"] for column in sa.inspect(conn).get_columns("ledger_transactions")}


def test_fresh_db_reaches_head_with_ownership_columns(tmp_path):
    database_path = tmp_path / "fresh.db"
    command.upgrade(_config(database_path), HEAD)
    columns = _columns(database_path)
    assert {"account_id", "instrument_id", "ownership_status"} <= columns

    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO ledger_transactions "
                "(transaction_id, account_id, instrument_id, entry_type, created_at) "
                "VALUES ('direct_insert', 'default', 'BTC-USDT-SWAP', "
                "'FUNDING_RECEIPT', :created_at)"
            ),
            {"created_at": CREATED_AT},
        )
    # A writer that bypasses LedgerService.record is not ownership-verified.
    assert _rows(database_path)[0]["ownership_status"] == "UNKNOWN"


def test_old_backfilled_default_is_corrected_without_guessing(tmp_path):
    database_path = tmp_path / "broken_0029.db"
    config = _config(database_path)
    command.upgrade(config, PREVIOUS)
    # Simulate a database where the pre-correction 0029 backfilled every
    # historical row to "default" without proof.
    _insert_ledger_transaction(database_path, transaction_id="guessed", account_id="default")

    command.upgrade(config, HEAD)
    row = _rows(database_path)[0]
    assert row["account_id"] == "default"  # retained for audit only
    assert row["ownership_status"] == "UNKNOWN"  # never counted as factual
    assert row["instrument_id"] is None


def test_legacy_null_ownership_stays_unknown(tmp_path):
    database_path = tmp_path / "legacy_null.db"
    config = _config(database_path)
    command.upgrade(config, PREVIOUS)
    _insert_ledger_transaction(database_path, transaction_id="legacy", account_id=None)

    command.upgrade(config, HEAD)
    row = _rows(database_path)[0]
    assert row["account_id"] is None
    assert row["ownership_status"] == "UNKNOWN"


def test_repeat_upgrade_is_idempotent(tmp_path):
    database_path = tmp_path / "repeat.db"
    config = _config(database_path)
    command.upgrade(config, PREVIOUS)
    _insert_ledger_transaction(database_path, transaction_id="one", account_id="default")

    command.upgrade(config, HEAD)
    first = _rows(database_path)
    command.upgrade(config, HEAD)
    second = _rows(database_path)
    assert first == second
    assert len(second) == 1
    assert second[0]["ownership_status"] == "UNKNOWN"


def test_downgrade_upgrade_does_not_duplicate_rows(tmp_path):
    database_path = tmp_path / "downgrade.db"
    config = _config(database_path)
    command.upgrade(config, HEAD)
    _insert_ledger_transaction(database_path, transaction_id="survivor", account_id="default")

    command.downgrade(config, PREVIOUS)
    command.upgrade(config, HEAD)
    rows = _rows(database_path)
    assert len(rows) == 1
    assert rows[0]["transaction_id"] == "survivor"
    assert rows[0]["ownership_status"] == "UNKNOWN"


def test_new_canonical_writes_are_verified_after_migration(tmp_path):
    database_path = tmp_path / "verified.db"
    config = _config(database_path)
    command.upgrade(config, HEAD)
    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO ledger_transactions "
                "(transaction_id, account_id, instrument_id, ownership_status, "
                "entry_type, created_at) "
                "VALUES ('canonical', 'default', 'BTC-USDT-SWAP', 'VERIFIED', "
                "'FUNDING_RECEIPT', :created_at)"
            ),
            {"created_at": CREATED_AT},
        )
    assert _rows(database_path)[0]["ownership_status"] == "VERIFIED"
