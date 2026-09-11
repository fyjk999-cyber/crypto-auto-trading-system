"""I01: real Alembic migration acceptance for Growth V2 cards."""

from __future__ import annotations

import io
import os
from contextlib import redirect_stdout

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from crypto_trader.persistence.database import create_sync_engine

PREVIOUS_HEAD = "0041_market_selection"
NEW_HEAD = "0042_growth_v2_cards"


def _config(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


def _seed_legacy_row(database_path) -> None:
    engine = create_sync_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO ai_compressed_experience "
                "(rule_id, title, content, source_episode_count, version, created_at) "
                "VALUES ('legacy_rule','Legacy','Legacy compressed',2,1,"
                "'2026-08-01 00:00:00')"
            )
        )
    engine.dispose()


def test_previous_head_to_new_head_repeat_downgrade_reupgrade(tmp_path):
    database_path = tmp_path / "growth_v2_migration.db"
    url = f"sqlite:///{database_path}"
    config = _config(url)

    command.upgrade(config, PREVIOUS_HEAD)
    _seed_legacy_row(database_path)

    command.upgrade(config, NEW_HEAD)
    engine = create_sync_engine(url)
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        card_columns = {
            column["name"]
            for column in inspector.get_columns("ai_compressed_experience")
        }
        tables = set(inspector.get_table_names())
    for required in (
        "experience_type",
        "account_id",
        "mode",
        "share_scope",
        "trigger_signature_json",
        "status",
        "known_at",
        "supersedes_rule_id",
    ):
        assert required in card_columns
    assert {"growth_card_versions", "growth_card_decision_traces"} <= tables

    with engine.connect() as connection:
        row = connection.execute(
            sa.text(
                "SELECT title, content, experience_type, status, account_id, mode, "
                "share_scope, known_at FROM ai_compressed_experience "
                "WHERE rule_id='legacy_rule'"
            )
        ).first()
    assert row is not None
    assert row[0] == "Legacy" and row[1] == "Legacy compressed"
    assert row[2] == "COMPRESSED_EXPERIENCE"
    assert row[3] == "WATCH"
    assert row[4] == "default" and row[5] == "PAPER"
    assert row[6] == "ACCOUNT_MODE"
    assert row[7] is not None
    engine.dispose()

    # repeat/current check is a no-op
    command.upgrade(config, NEW_HEAD)

    # downgrade removes only V2 objects, the legacy row survives.
    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_sync_engine(url)
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        card_columns = {
            column["name"]
            for column in inspector.get_columns("ai_compressed_experience")
        }
        tables = set(inspector.get_table_names())
        row = connection.execute(
            sa.text("SELECT title FROM ai_compressed_experience WHERE rule_id='legacy_rule'")
        ).first()
    assert "trigger_signature_json" not in card_columns
    assert "growth_card_versions" not in tables
    assert row is not None and row[0] == "Legacy"
    engine.dispose()

    # re-upgrade works
    command.upgrade(config, NEW_HEAD)
    engine = create_sync_engine(url)
    with engine.connect() as connection:
        card_columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("ai_compressed_experience")
        }
    assert "trigger_signature_json" in card_columns
    engine.dispose()


def test_postgresql_sql_compilation_for_new_revision():
    config = _config("postgresql://growth:growth@localhost:5432/growth")
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.upgrade(config, f"{PREVIOUS_HEAD}:{NEW_HEAD}", sql=True)
    sql = buffer.getvalue().upper()
    assert "CREATE TABLE GROWTH_CARD_VERSIONS" in sql
    assert "CREATE TABLE GROWTH_CARD_DECISION_TRACES" in sql
    assert "ALTER TABLE AI_COMPRESSED_EXPERIENCE ADD COLUMN TRIGGER_SIGNATURE_JSON" in sql
    assert "UNIQUE (CARD_RULE_ID, VERSION, PROPOSAL_HASH)" in sql


@pytest.mark.skipif(
    not os.environ.get("GROWTH_V2_POSTGRES_URL"),
    reason="GROWTH_V2_POSTGRES_URL not provided; real PostgreSQL run NOT_VERIFIED",
)
def test_postgresql_real_database_if_available():
    url = os.environ["GROWTH_V2_POSTGRES_URL"]
    config = _config(url)
    command.upgrade(config, NEW_HEAD)
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert "growth_card_versions" in set(inspector.get_table_names())
        columns = {
            column["name"]
            for column in inspector.get_columns("ai_compressed_experience")
        }
        assert "share_scope" in columns
    command.downgrade(config, PREVIOUS_HEAD)
    engine.dispose()
