"""P1/P5 migration acceptance for valuation truth batch fields."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from crypto_trader.persistence.database import create_sync_engine

PREVIOUS = "0032_ledger_ownership"
HEAD = "0033_valuation_truth"


def _config(database_path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def _columns(database_path, table: str) -> dict:
    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.connect() as conn:
        return {
            column["name"]: column
            for column in sa.inspect(conn).get_columns(table)
        }


def test_valuation_truth_columns_and_nullable_equity(tmp_path):
    database_path = tmp_path / "valuation.db"
    config = _config(database_path)
    command.upgrade(config, PREVIOUS)
    command.upgrade(config, HEAD)

    batch_columns = _columns(database_path, "valuation_batches")
    assert "drawdown_ratio" in batch_columns
    assert "market_as_of" in batch_columns

    snapshot_columns = _columns(database_path, "equity_snapshots")
    assert snapshot_columns["peak_equity"]["nullable"] is True
    assert snapshot_columns["peak_adjusted_equity"]["nullable"] is True
    assert snapshot_columns["drawdown"]["nullable"] is True
    assert snapshot_columns["cash_flow_adjusted_equity"]["nullable"] is True


def test_upgrade_head_is_idempotent_and_preserves_existing_peak(tmp_path):
    database_path = tmp_path / "idempotent.db"
    config = _config(database_path)
    command.upgrade(config, HEAD)
    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO equity_snapshots "
                "(account_id, currency, current_equity, raw_equity, "
                "external_cash_flow_adjustment, period_external_cash_flow, "
                "cumulative_external_cash_flow, cash_flow_adjusted_equity, "
                "peak_equity, peak_adjusted_equity, drawdown, valuation_status, "
                "valuation_source, valuation_as_of, created_at) "
                "VALUES ('default', 'USDT', '100', '100', '0', '0', '0', '100', "
                "'100', '100', '0', 'HEALTHY', 'TEST', :now, :now)"
            ),
            {"now": "2026-09-10 04:00:00"},
        )
    command.upgrade(config, HEAD)
    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT peak_adjusted_equity, drawdown FROM equity_snapshots "
                "ORDER BY id LIMIT 1"
            )
        ).one()
    assert row[0] == "100"
    assert row[1] == "0"
