#!/usr/bin/env python3
"""Read-only diagnostics for the growth-learning pipeline (G00/G05 dry-run).

Safety contract
---------------
* Source databases are opened with ``file:...?mode=ro`` plus
  ``PRAGMA query_only=ON``.  The script never writes to the source file,
  never deletes a WAL/SHM file and never uses ``immutable=1``.
* Live WAL databases are read through the SQLite backup API into a private
  temporary directory, so a checkpointed main file is not mistaken for the
  whole database.
* Only counts, statuses, timestamps, hashes and sanitized identifiers are
  emitted.  No environment variables, API keys or credential material are
  read by this script.
* ``import-inventory`` is read-only on the source and writes only its JSON
  plan to ``--plan-out``.  It cannot import into any database.

Usage examples
--------------
    python scripts/growth_system_dry_run.py manifest \
        --db fullmarket=/abs/path/data/crypto_trader.db \
        --out docs/growth-system/SOURCE_MANIFEST.json
    python scripts/growth_system_dry_run.py episodes --db /abs/path/data/crypto_trader.db
    python scripts/growth_system_dry_run.py review-status --db /abs/path/data/crypto_trader.db
    python scripts/growth_system_dry_run.py import-inventory \
        --source /abs/path/data/crypto_trader.db --plan-out /tmp/import_plan.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime

MANIFEST_VERSION = "growth-source-manifest-v1"

EPISODE_STATUS_QUERY = """
select review_status, count(*)
from trade_episodes
where factual = 1
group by review_status
order by review_status
"""

KEY_TABLES = (
    "trade_episodes",
    "ai_trade_episodes",
    "trade_memory_records",
    "ai_trade_reviews",
    "ai_market_patterns",
    "ai_coin_profiles",
    "ai_compressed_experience",
    "daily_review_runs",
    "daily_review_results",
    "learning_lessons",
    "learning_pattern_candidates",
    "learning_review_jobs",
    "llm_decisions",
    "llm_usage",
    "decision_evidence",
    "engine_runs",
    "fills",
    "orders",
    "trade_plans",
    "risk_decisions",
    "runtime_leases",
    "accounts_projection",
)


def utc_iso(ts: float | None = None) -> str:
    moment = datetime.fromtimestamp(ts, tz=UTC) if ts is not None else datetime.now(UTC)
    return moment.isoformat()


def sha256_file(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except FileNotFoundError:
        return None


def open_snapshot(path: str) -> tuple[sqlite3.Connection, tempfile.TemporaryDirectory]:
    """Return a consistent read-only snapshot of *path*.

    The caller owns the returned connection and must call ``close_snapshot``.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    holder = tempfile.TemporaryDirectory(prefix="growth-snapshot-")
    destination = os.path.join(holder.name, "snapshot.db")
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15.0)
    try:
        source.execute("PRAGMA query_only=ON")
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    connection = sqlite3.connect(destination)
    connection.row_factory = sqlite3.Row
    return connection, holder


def close_snapshot(connection: sqlite3.Connection, holder: tempfile.TemporaryDirectory) -> None:
    connection.close()
    holder.cleanup()


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "select 1 from sqlite_master where type='table' and name=?", (table,)
    ).fetchone()
    return row is not None


def scalar(connection: sqlite3.Connection, sql: str, params: tuple = ()):
    try:
        row = connection.execute(sql, params).fetchone()
    except sqlite3.Error as exc:
        return f"ERR:{type(exc).__name__}:{exc}"
    return row[0] if row is not None else None


def rows(connection: sqlite3.Connection, sql: str, params: tuple = ()) -> list[list]:
    try:
        return [list(row) for row in connection.execute(sql, params)]
    except sqlite3.Error as exc:
        return [["ERR", f"{type(exc).__name__}: {exc}"]]


def database_inventory(label: str, path: str) -> dict:
    record: dict = {
        "label": label,
        "path": path,
        "exists": os.path.exists(path),
    }
    if not record["exists"]:
        return record
    stat = os.stat(path)
    record.update(
        size_bytes=stat.st_size,
        mtime_utc=utc_iso(stat.st_mtime),
        sha256_main=sha256_file(path),
        snapshot_method="sqlite_backup_api_from_readonly_connection",
    )
    wal = path + "-wal"
    shm = path + "-shm"
    record["wal"] = {
        "present": os.path.exists(wal),
        "size_bytes": os.path.getsize(wal) if os.path.exists(wal) else 0,
        "sha256_at_read_time": sha256_file(wal),
    }
    record["shm_present"] = os.path.exists(shm)

    connection, holder = open_snapshot(path)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type='table' order by name"
            )
        ]
        record["table_count"] = len(tables)
        record["alembic_revision"] = (
            [row[0] for row in connection.execute("select version_num from alembic_version")]
            if table_exists(connection, "alembic_version")
            else []
        )
        counts: dict[str, int | str] = {}
        for table in KEY_TABLES:
            counts[table] = (
                scalar(connection, f"select count(*) from {table}")
                if table_exists(connection, table)
                else None
            )
        record["key_table_counts"] = counts

        if table_exists(connection, "trade_episodes"):
            record["trade_episodes"] = {
                "total": counts.get("trade_episodes"),
                "factual": scalar(
                    connection, "select count(*) from trade_episodes where factual = 1"
                ),
                "review_status": {
                    row[0]: row[1] for row in connection.execute(EPISODE_STATUS_QUERY)
                },
                "closed_at_min": scalar(connection, "select min(closed_at) from trade_episodes"),
                "closed_at_max": scalar(connection, "select max(closed_at) from trade_episodes"),
                "duplicate_trade_plan_ids": scalar(
                    connection,
                    "select count(*) from (select trade_plan_id from trade_episodes "
                    "group by trade_plan_id having count(*) > 1)",
                ),
                "null_closed_at": scalar(
                    connection, "select count(*) from trade_episodes where closed_at is null"
                ),
                "direction_counts": {
                    row[0]: row[1]
                    for row in connection.execute(
                        "select direction, count(*) from trade_episodes group by direction"
                    )
                },
            }
        if table_exists(connection, "daily_review_runs"):
            columns = {
                row[1] for row in connection.execute("pragma table_info(daily_review_runs)")
            }
            status_column = "status" if "status" in columns else None
            record["daily_review_runs"] = {
                "count": counts.get("daily_review_runs"),
                "status_column_present": status_column is not None,
                "status": (
                    {
                        row[0]: row[1]
                        for row in connection.execute(
                            f"select {status_column}, count(*) from daily_review_runs "
                            f"group by {status_column}"
                        )
                    }
                    if status_column
                    else None
                ),
                "min_review_date": scalar(
                    connection, "select min(review_date) from daily_review_runs"
                ),
                "max_review_date": scalar(
                    connection, "select max(review_date) from daily_review_runs"
                ),
                "recent": rows(
                    connection,
                    "select review_date, "
                    + (status_column or "'LEGACY_SCHEMA'")
                    + " as status, trade_count, win_rate, profit_factor from daily_review_runs "
                    "order by review_date desc limit 10",
                ),
            }
        if table_exists(connection, "accounts_projection"):
            record["accounts_projection"] = rows(
                connection,
                "select account_id, currency, equity, version, updated_at "
                "from accounts_projection order by id limit 5",
            )
        if table_exists(connection, "engine_runs"):
            columns = {row[1] for row in connection.execute("pragma table_info(engine_runs)")}
            order_column = "id" if "id" in columns else "started_at"
            select_columns = [
                column
                for column in ("run_id", "state", "mode", "strategy_id", "started_at", "ended_at")
                if column in columns
            ]
            record["engine_runs_recent"] = rows(
                connection,
                f"select {', '.join(select_columns)} from engine_runs "
                f"order by {order_column} desc limit 5",
            )
        if table_exists(connection, "runtime_leases"):
            record["runtime_leases"] = rows(
                connection,
                "select lease_key, owner_id, acquired_at, expires_at, fence_generation "
                "from runtime_leases order by id desc limit 5",
            )
        if table_exists(connection, "llm_usage"):
            record["llm_usage_range"] = rows(
                connection,
                "select min(created_at), max(created_at), count(*) from llm_usage",
            )
        if table_exists(connection, "decision_evidence"):
            record["decision_evidence_range"] = rows(
                connection,
                "select min(created_at), max(created_at), count(*) from decision_evidence",
            )
    finally:
        close_snapshot(connection, holder)
    return record


def cmd_manifest(args: argparse.Namespace) -> int:
    databases = []
    for entry in args.db:
        label, _, path = entry.partition("=")
        if not path:
            print(f"invalid --db value (expected LABEL=PATH): {entry}", file=sys.stderr)
            return 2
        databases.append(database_inventory(label, os.path.abspath(path)))
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": utc_iso(),
        "harness": {
            "task_id": args.task_id,
            "base_sha": args.base_sha,
            "worktree": args.worktree,
            "candidate_sha": None,
            "note": "candidate_sha is bound in the review receipt after commit",
        },
        "databases": databases,
        "claims_not_verified_by_this_manifest": [
            "provider request totals must be defined table-by-table "
            "(attempts vs tool calls vs successful calls)",
            "worktree SHA does not prove the SHA of the running process",
            "cross-database counts must never be added into one case count",
        ],
    }
    payload = json.dumps(manifest, indent=2, default=str) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(payload)
        print(f"wrote {args.out}")
    else:
        print(payload)
    return 0


def cmd_episodes(args: argparse.Namespace) -> int:
    path = os.path.abspath(args.db)
    connection, holder = open_snapshot(path)
    try:
        if not table_exists(connection, "trade_episodes"):
            print(json.dumps({"db": path, "error": "trade_episodes table absent"}))
            return 1
        status = {
            row[0]: row[1]
            for row in connection.execute(
                "select review_status, count(*) from trade_episodes where factual = 1 "
                "group by review_status"
            )
        }
        by_date = rows(
            connection,
            "select substr(closed_at, 1, 10) as day, review_status, count(*) "
            "from trade_episodes where factual = 1 group by 1, 2 order by 1",
        )
        print(
            json.dumps(
                {
                    "db": path,
                    "snapshot_method": "sqlite_backup_api_from_readonly_connection",
                    "eligibility_definition": (
                        "factual=1 and closed_at is not null; review_status decides stage "
                        "PENDING/REVIEWED; quarantine is represented by review_status values "
                        "other than PENDING/REVIEWED and by missing episode rows for closed "
                        "trade_plans (see build_for_closed_plan fail-closed reasons)"
                    ),
                    "review_status": status,
                    "requested_date": args.date,
                    "all_dates": by_date,
                    "min_closed_at": scalar(
                        connection,
                        "select min(closed_at) from trade_episodes where factual = 1",
                    ),
                    "max_closed_at": scalar(
                        connection,
                        "select max(closed_at) from trade_episodes where factual = 1",
                    ),
                },
                indent=2,
                default=str,
            )
        )
    finally:
        close_snapshot(connection, holder)
    return 0


def cmd_review_status(args: argparse.Namespace) -> int:
    path = os.path.abspath(args.db)
    connection, holder = open_snapshot(path)
    try:
        payload: dict = {
            "db": path,
            "snapshot_method": "sqlite_backup_api_from_readonly_connection",
            "tables": {},
        }
        if table_exists(connection, "daily_review_runs"):
            columns = {
                row[1] for row in connection.execute("pragma table_info(daily_review_runs)")
            }
            status = "status" if "status" in columns else None
            payload["tables"]["daily_review_runs"] = {
                "count": scalar(connection, "select count(*) from daily_review_runs"),
                "status": (
                    {
                        row[0]: row[1]
                        for row in connection.execute(
                            f"select {status}, count(*) from daily_review_runs group by {status}"
                        )
                    }
                    if status
                    else "LEGACY_SCHEMA_STATUS_COLUMN_ABSENT"
                ),
                "newest": scalar(
                    connection, "select max(review_date) from daily_review_runs"
                ),
            }
        for table in ("ai_trade_reviews", "trade_episodes"):
            if table_exists(connection, table):
                payload["tables"][table] = {
                    "count": scalar(connection, f"select count(*) from {table}")
                }
                if table == "trade_episodes":
                    payload["tables"][table]["by_review_status"] = {
                        row[0]: row[1]
                        for row in connection.execute(
                            "select review_status, count(*) from trade_episodes "
                            "where factual = 1 group by review_status"
                        )
                    }
        print(json.dumps(payload, indent=2, default=str))
    finally:
        close_snapshot(connection, holder)
    return 0


def cmd_import_inventory(args: argparse.Namespace) -> int:
    """Dry-run only: inventory legacy observations, never write a target DB."""
    path = os.path.abspath(args.source)
    connection, holder = open_snapshot(path)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type='table' "
                "and (name like '%episode%' or name like '%memory%' or name like '%lesson%') "
                "order by name"
            )
        ]
        inventory = []
        for table in tables:
            columns = {
                row[1] for row in connection.execute(f"pragma table_info({table})")
            }
            identity = (
                "episode_id"
                if "episode_id" in columns
                else "decision_id"
                if "decision_id" in columns
                else "id"
                if "id" in columns
                else None
            )
            has_closed = "closed_at" in columns or "exit_price" in columns or "pnl" in columns
            inventory.append(
                {
                    "table": table,
                    "count": scalar(connection, f"select count(*) from {table}"),
                    "identity_column": identity,
                    "usable_as_legacy_observation": bool(identity and has_closed),
                    "columns": sorted(columns),
                }
            )
        plan = {
            "plan_version": "growth-legacy-import-plan-v1",
            "generated_at": utc_iso(),
            "source_db": path,
            "source_sha256": sha256_file(path),
            "dry_run": True,
            "target_db_written": False,
            "inventory": inventory,
            "namespace_rule": (
                "namespace = sha256(source_db_sha256 + '|' + table + '|' + source_id)"
            ),
            "strong_dedup_rule": (
                "same namespace only; near-duplicate symbol/time/pnl stays "
                "DUPLICATE_SUSPECT and is never merged automatically"
            ),
            "default_disposition": (
                "LEGACY_OBSERVATION unless ledger/fill proof is present; missing proof "
                "-> QUARANTINED"
            ),
        }
        payload = json.dumps(plan, indent=2, default=str) + "\n"
        if args.plan_out:
            with open(args.plan_out, "w", encoding="utf-8") as handle:
                handle.write(payload)
            print(f"wrote {args.plan_out}")
        else:
            print(payload)
    finally:
        close_snapshot(connection, holder)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="read-only inventory for one or more DBs")
    manifest.add_argument("--db", action="append", required=True, metavar="LABEL=PATH")
    manifest.add_argument("--out")
    manifest.add_argument("--base-sha", default="UNKNOWN")
    manifest.add_argument("--worktree", default="UNKNOWN")
    manifest.add_argument("--task-id", default="growth-learning-pipeline")
    manifest.set_defaults(func=cmd_manifest)

    episodes = sub.add_parser("episodes", help="factual episode eligibility by status/date")
    episodes.add_argument("--db", required=True)
    episodes.add_argument("--date")
    episodes.set_defaults(func=cmd_episodes)

    review_status = sub.add_parser("review-status", help="daily review and episode review status")
    review_status.add_argument("--db", required=True)
    review_status.set_defaults(func=cmd_review_status)

    import_inventory = sub.add_parser(
        "import-inventory", help="read-only legacy import inventory (writes plan JSON only)"
    )
    import_inventory.add_argument("--source", required=True)
    import_inventory.add_argument("--plan-out")
    import_inventory.set_defaults(func=cmd_import_inventory)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
