"""P3 migration acceptance for funding coverage proof columns."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from crypto_trader.persistence.database import create_sync_engine

HEAD = "0034_funding_proof"


def _config(database_path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def test_coverage_proof_columns_exist_and_repeat_upgrade_is_safe(tmp_path):
    database_path = tmp_path / "coverage.db"
    config = _config(database_path)
    command.upgrade(config, HEAD)
    command.upgrade(config, HEAD)
    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.connect() as conn:
        columns = {
            column["name"]: column
            for column in sa.inspect(conn).get_columns("funding_coverage_windows")
        }
    assert {"fetched_count", "window_event_count", "boundary_proof"} <= set(columns)
    assert columns["fetched_count"]["nullable"] is False
    assert columns["window_event_count"]["nullable"] is False
    assert columns["boundary_proof"]["nullable"] is False
