"""P8 migration acceptance for daily review claim owner/deadline."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from crypto_trader.persistence.database import create_sync_engine

HEAD = "0035_review_claim"


def _config(database_path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def test_daily_review_claim_columns_and_repeat_upgrade(tmp_path):
    database_path = tmp_path / "review_claim.db"
    config = _config(database_path)
    command.upgrade(config, HEAD)
    command.upgrade(config, HEAD)
    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.connect() as conn:
        columns = {
            column["name"]: column
            for column in sa.inspect(conn).get_columns("daily_review_runs")
        }
    assert "owner" in columns
    assert "claim_deadline_at" in columns
    assert columns["owner"]["nullable"] is True
    assert columns["claim_deadline_at"]["nullable"] is True
