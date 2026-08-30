"""One-time controlled SQLite -> PostgreSQL data migration (cloud deploy).

Preserves IDs and timestamps exactly. Does NOT fabricate records: tables are
copied verbatim row-by-row, and any table present in the source but absent
from the destination schema is reported and SKIPPED (never invented).

Usage (on the cloud server, after `alembic upgrade head` against PG):
    python3 scripts/sqlite_to_postgres_migrate.py \
        --source data/crypto_trader.db \
        --destination postgresql+psycopg2://crypto_trader:PW@127.0.0.1:5432/crypto_trader \
        --report docs/CLOUD_DATA_MIGRATION_REPORT.md

Safety:
- refuses to run against the canonical SQLite as DESTINATION
- refuses to copy into non-empty PG tables unless --truncate is given
- never prints connection strings or secrets
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import MetaData, create_engine, insert, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

CHUNK = 500
SKIP_PREFIXES = ("sqlite_",)


def topological_order(names: list[str], fks: dict[str, set[str]]) -> list[str]:
    order, done, remaining = [], set(), set(names)
    while remaining:
        progressed = False
        for name in sorted(remaining):
            deps = fks.get(name, set()) & remaining
            if deps <= done:
                order.append(name)
                done.add(name)
                remaining.discard(name)
                progressed = True
        if not progressed:  # cyclic/no explicit order — append rest sorted
            order.extend(sorted(remaining))
            break
    return order


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default="data/crypto_trader.db")
    ap.add_argument("--destination", required=True)
    ap.add_argument("--report", default="docs/CLOUD_DATA_MIGRATION_REPORT.md")
    ap.add_argument("--truncate", action="store_true",
                    help="truncate non-empty destination tables before copy")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    dest_url = args.destination
    if "sqlite" in dest_url.split(":")[0]:
        print("FATAL: destination must be PostgreSQL, not SQLite", file=sys.stderr)
        return 2

    src_path = Path(args.source)
    if not src_path.exists():
        print(f"FATAL: source {src_path} missing", file=sys.stderr)
        return 2

    # WAL checkpoint so idle WAL data is readable by the migration connection.
    raw = sqlite3.connect(str(src_path))
    try:
        raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        raw.close()

    src_engine = create_engine(f"sqlite:///{src_path}")
    dst_engine = create_engine(dest_url)

    src_meta, dst_meta = MetaData(), MetaData()
    src_meta.reflect(bind=src_engine)
    dst_meta.reflect(bind=dst_engine)

    src_tables = {t for t in src_meta.tables if not t.startswith(SKIP_PREFIXES)}
    dst_tables = set(dst_meta.tables)
    common = sorted(src_tables & dst_tables)
    missing_in_dst = sorted(src_tables - dst_tables)

    fks = {
        name: {fk.referred_table for fk in table.foreign_keys if fk.referred_table in common}
        for name, table in ((n, src_meta.tables[n]) for n in common)
    }
    order = topological_order(common, fks)

    # Determine destination emptiness up front.
    empty_issue: list[str] = []
    with dst_engine.connect() as dconn:
        for name in common:
            cols = list(dst_meta.tables[name].c)
            if not cols:
                continue
            probe = dconn.execute(select(dst_meta.tables[name].c[cols[0]]).limit(1)).first()
            if probe is not None:
                empty_issue.append(name)
    if empty_issue and not args.truncate:
        print(f"FATAL: destination tables not empty: {empty_issue}. "
              "Use --truncate only for a deliberate re-run.", file=sys.stderr)
        return 2

    print(f"tables to copy: {len(common)}; missing in destination schema: {len(missing_in_dst)}")
    results: list[tuple[str, int, int, str]] = []

    if args.dry_run:
        for name in order:
            with src_engine.connect() as sconn:
                n = sconn.exec_driver_sql(f'SELECT COUNT(*) FROM "{name}"').scalar()
            results.append((name, int(n), -1, "DRY-RUN"))
        for name, s, _d, _st in results:
            print(f"  {name:40s} source={s}")
        return 0

    if empty_issue and args.truncate:
        with dst_engine.begin() as dconn:
            for name in reversed(order):
                dconn.exec_driver_sql(f'TRUNCATE TABLE "{name}" CASCADE')
            print(f"truncated {len(order)} destination tables")

    for name in order:
        src_t = src_meta.tables[name]
        dst_t = dst_meta.tables[name]
        copied = 0
        dest_n = -1
        status = ""
        try:
            # Validate DDL compatibility once per table (PG dialect compile).
            CreateTable(dst_t).compile(dialect=postgresql.dialect())
            with src_engine.connect() as sconn:
                rows = sconn.execute(select(src_t)).mappings().all()
            for i in range(0, len(rows), CHUNK):
                batch = [dict(r) for r in rows[i:i + CHUNK]]
                with dst_engine.begin() as dconn:
                    dconn.execute(insert(dst_t), batch)
                copied += len(batch)
            with dst_engine.connect() as dconn:
                dest_n = int(dconn.exec_driver_sql(f'SELECT COUNT(*) FROM "{name}"').scalar())
            status = "OK" if dest_n == copied else "COUNT_MISMATCH"
        except Exception as exc:  # noqa: BLE001 — record and continue other tables
            status = f"ERROR: {exc.__class__.__name__}: {str(exc)[:160]}"
            copied = -1
        results.append((name, copied, dest_n, status))
        print(f"  {name:40s} copied={copied} dest={dest_n} status={status}")

    ok = sum(1 for r in results if r[3] == "OK" and r[1] == r[2])
    print(f"\ncopied-clean={ok}/{len(common)}")
    _write_report(args, results, missing_in_dst)
    return 0 if ok == len(common) and not missing_in_dst else 1


def _write_report(args, results, missing_in_dst) -> None:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    lines = [
        "# CLOUD_DATA_MIGRATION_REPORT",
        "",
        f"- Generated: {now}",
        f"- Source: `{args.source}` (canonical SQLite, WAL checkpointed)",
        "- Destination: PostgreSQL 16 (cloud, `crypto_trader` DB)",
        f"- Dry-run: {args.dry_run}",
        f"- Tables missing in destination schema (SKIPPED, never fabricated): "
        f"{', '.join(missing_in_dst) or '(none)'}",
        "",
        "| table | source rows | destination rows | status |",
        "|---|---|---|---|",
    ]
    for name, s, d, st in results:
        lines.append(f"| {name} | {s} | {d} | {st} |")
    lines += ["", "## Continuity verdict",
              "- DATA_CONTINUITY_VALIDATED = "
              f"{'YES' if all(r[3] == 'OK' and r[1] == r[2] for r in results) else 'NO'}",
              ""]
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text("\n".join(lines), encoding="utf-8")
    print(f"report written: {args.report}")


if __name__ == "__main__":
    raise SystemExit(main())
