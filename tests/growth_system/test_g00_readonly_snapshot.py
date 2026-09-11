"""G00: read-only snapshot contract tests (TEST_ONLY)."""

from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "growth_system_dry_run.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("growth_system_dry_run", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def dry_run():
    return _load_module()


def _make_episode_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        create table trade_episodes (
            episode_id text primary key,
            trade_plan_id text not null unique,
            symbol text not null,
            direction text not null,
            factual integer not null default 1,
            review_status text not null default 'PENDING',
            closed_at text,
            created_at text
        );
        create table daily_review_runs (
            review_date text primary key,
            daily_pnl text,
            trade_count integer,
            win_rate text,
            profit_factor text,
            created_at text
        );
        insert into trade_episodes values
            ('episode_a','plan_a','BTCUSDT','LONG',1,'PENDING','2026-09-09 10:00:00',null),
            ('episode_b','plan_b','ETHUSDT','SHORT',1,'REVIEWED','2026-09-09 11:00:00',null);
        insert into daily_review_runs values ('2026-09-09','0',0,'0','999',null);
        """
    )
    connection.commit()
    connection.close()


def test_dry_run_never_uses_immutable_and_opens_read_only(dry_run):
    text = SCRIPT.read_text(encoding="utf-8")
    # Strip the module docstring (it explicitly forbids immutable mode); the
    # executable source must never mention it.
    executable = text.split('"""', 2)[2]
    assert "immutable" not in executable
    assert "mode=ro" in text
    assert "PRAGMA query_only=ON" in text


def test_snapshot_sees_uncheckpointed_wal_rows(dry_run, tmp_path, temp_db_path):
    source = temp_db_path
    writer = sqlite3.connect(source)
    writer.execute("pragma journal_mode=WAL")
    writer.execute("create table t (id integer primary key, value text)")
    writer.execute("insert into t(value) values ('committed-but-only-in-wal')")
    writer.commit()
    # Keep the writer open and do not checkpoint: a main-file-only copy would
    # miss this row.  The backup API snapshot must see it.
    connection, holder = dry_run.open_snapshot(str(source))
    try:
        rows = connection.execute("select value from t").fetchall()
        assert [row[0] for row in rows] == ["committed-but-only-in-wal"]
    finally:
        dry_run.close_snapshot(connection, holder)
        writer.close()


def test_inventory_is_read_only_and_reports_status(dry_run, temp_db_path):
    _make_episode_db(temp_db_path)
    before = hashlib.sha256(temp_db_path.read_bytes()).hexdigest()
    inventory = dry_run.database_inventory("temp", str(temp_db_path))
    after = hashlib.sha256(temp_db_path.read_bytes()).hexdigest()
    assert before == after, "read-only inventory must not modify the source database"
    assert inventory["trade_episodes"]["factual"] == 2
    assert inventory["trade_episodes"]["review_status"] == {"PENDING": 1, "REVIEWED": 1}
    assert inventory["key_table_counts"]["trade_episodes"] == 2
    assert inventory["daily_review_runs"]["status_column_present"] is False


def test_episodes_command_reports_eligible_and_reviewed(dry_run, temp_db_path, capsys):
    _make_episode_db(temp_db_path)
    exit_code = dry_run.main(["episodes", "--db", str(temp_db_path)])
    assert exit_code == 0
    payload = capsys.readouterr().out
    assert '"PENDING": 1' in payload
    assert '"REVIEWED": 1' in payload
