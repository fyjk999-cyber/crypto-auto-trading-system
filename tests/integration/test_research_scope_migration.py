from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from crypto_trader.persistence.database import create_sync_engine

PREVIOUS = "0038_llm_evidence"
HEAD = "0039_research_scope"


def _config(database_path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def test_research_scope_migration_preserves_legacy_rows_and_is_repeatable(tmp_path):
    database_path = tmp_path / "research-scope.db"
    config = _config(database_path)
    command.upgrade(config, PREVIOUS)

    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO research_reports "
                "(research_id, summary, conclusion, confidence, created_at) "
                "VALUES ('legacy', 'summary', 'conclusion', 0.5, "
                "'2026-01-01 00:00:00')"
            )
        )

    command.upgrade(config, HEAD)
    command.upgrade(config, HEAD)

    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.connect() as conn:
        columns = {
            column["name"]
            for column in sa.inspect(conn).get_columns("research_reports")
        }
        row = conn.execute(
            sa.text(
                "SELECT scope_type, symbol, regime FROM research_reports "
                "WHERE research_id = 'legacy'"
            )
        ).one()
    assert {"scope_type", "symbol", "regime"} <= columns
    assert row[0] == "GLOBAL"
    assert row[1] is None
    assert row[2] is None

    command.downgrade(config, PREVIOUS)
    command.upgrade(config, HEAD)
