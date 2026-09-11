#!/usr/bin/env python3
"""Enable and run the built-in LLM structured-review / learning worker.

This does NOT start the trading runtime and does NOT place orders.  It targets
one canonical factual database, migrates it to the current schema, then runs
the existing ``DailyReviewScheduler`` with the existing DeepSeek-backed
``StructuredReviewRunner``.  The provider key is loaded from the project's
macOS Keychain helper into memory and is never printed or persisted.

Usage:
    .venv/bin/python scripts/growth_review_worker.py \
        --db /path/to/crypto_trader.db \
        --date 2026-09-09
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

DEFAULT_KEYCHAIN_HELPER = Path(
    "/Users/huhongjie/Documents/ChatGPT/"
    "crypto-auto-trading-system-fullmarket/scripts/deepseek-keychain.swift"
)
DEFAULT_DB = Path(
    "/Users/huhongjie/Documents/ChatGPT/"
    "crypto-auto-trading-system-canonical-clean/data/crypto_trader.db"
)


def load_keychain_credential(helper: Path) -> str:
    """Load the provider key into memory only; never log its value."""
    if not helper.exists():
        raise RuntimeError(f"keychain helper not found: {helper}")
    result = subprocess.run(
        ["swift", str(helper), "load"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    key = (result.stdout or "").strip()
    if result.returncode != 0 or not key:
        raise RuntimeError("provider credential is not configured in Keychain")
    return key


def _readonly_connection(path: Path) -> sqlite3.Connection:
    """Open read-only when possible; WAL snapshots may require a RW handle.

    The handle is always put into ``query_only`` mode, so this remains a
    read-only use even when SQLite needs a writable handle for the WAL index.
    """
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15.0)
    except sqlite3.OperationalError:
        connection = sqlite3.connect(f"file:{path}?mode=rw", uri=True, timeout=15.0)
    connection.execute("PRAGMA query_only=ON")
    return connection


def backup_database(path: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = out_dir / f"{path.stem}-pre-llm-review-{stamp}.db"
    source = _readonly_connection(path)
    target = sqlite3.connect(destination)
    source.backup(target)
    target.close()
    source.close()
    return destination


def migrate_database(path: Path) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "head")

    from crypto_trader.learning.growth_models import GrowthBase
    from crypto_trader.persistence.database import create_sync_engine

    engine = create_sync_engine(f"sqlite:///{path}")
    try:
        GrowthBase.metadata.create_all(engine)
    finally:
        engine.dispose()


def pending_dates(path: Path) -> list[str]:
    connection = _readonly_connection(path)
    try:
        rows = connection.execute(
            "select distinct substr(closed_at,1,10) from trade_episodes "
            "where factual=1 and (review_status is null or review_status!='REVIEWED') "
            "order by 1"
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        connection.close()


async def run(args) -> dict:
    from crypto_trader.governance.scheduler import DailyReviewScheduler
    from crypto_trader.learning.growth_attribution import DailyCardLearner
    from crypto_trader.learning.growth_structured_review import StructuredReviewRunner
    from crypto_trader.llm_chief.provider import DeepSeekProvider
    from crypto_trader.persistence.database import Database

    provider_key = load_keychain_credential(Path(args.keychain_helper))
    os.environ["DEEPSEEK_API_KEY"] = provider_key
    model = args.model or os.environ.get("LLM_MODEL") or "deepseek-flash"
    os.environ["LLM_MODEL"] = model
    os.environ.setdefault("LLM_BASE_URL", "https://api.deepseek.com")

    database_path = Path(args.db).resolve()  # noqa: ASYNC240
    backup = backup_database(database_path, Path(args.backup_dir))
    migrate_database(database_path)

    dates = args.date or pending_dates(database_path)
    database = Database(f"sqlite+aiosqlite:///{database_path}")
    provider = DeepSeekProvider()
    if not provider.healthy():
        raise RuntimeError("provider unhealthy after credential load")
    runner = StructuredReviewRunner(
        database.session_factory,
        provider,
        owner=args.owner,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        max_tokens=args.max_tokens,
        thinking=args.thinking,
        bootstrap_cards=True,
        max_episodes_per_run=args.max_episodes,
    )
    scheduler = DailyReviewScheduler(
        database.session_factory,
        canonical_only=True,
        owner=args.owner,
        claim_lease_seconds=3600,
        account_id=args.account_id,
        mode=args.mode,
        profile_version=args.profile_version,
        card_learner=DailyCardLearner(database.session_factory),
        structured_review_runner=runner,
    )
    results: list[dict] = []
    try:
        for date in dates[: args.max_dates]:
            result = await scheduler.run_once(date)
            results.append(result)
            structured = result.get("structured_review") or {}
            if structured.get("stop_on_provider_error"):
                break
            if structured.get("status") == "FAILED" and structured.get("error_type"):
                break
    finally:
        await database.close()

    report = {
        "db": str(database_path),
        "backup": str(backup),
        "model": model,
        "provider": provider.name,
        "dates": results,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(  # noqa: ASYNC240
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--date", action="append", default=[])
    parser.add_argument("--max-dates", type=int, default=7)
    parser.add_argument("--max-episodes", type=int, default=None)
    parser.add_argument("--keychain-helper", default=str(DEFAULT_KEYCHAIN_HELPER))
    parser.add_argument("--model", default=None)
    parser.add_argument("--owner", default="growth-llm-backfill")
    parser.add_argument("--account-id", default="default")
    parser.add_argument("--mode", default="PAPER")
    parser.add_argument("--profile-version", default="growth-structured-review-v1")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument(
        "--thinking",
        action=__import__("argparse").BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--backup-dir",
        default=str(ROOT / ".ops-growth-v2" / "paper_review" / "backups"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / ".ops-growth-v2" / "paper_review" / "llm_review_run.json"),
    )
    args = parser.parse_args()
    report = asyncio.run(run(args))
    sanitized = {
        "db": report["db"],
        "backup": report["backup"],
        "model": report["model"],
        "provider": report["provider"],
        "dates": [
            {
                "date": row.get("date"),
                "status": row.get("status"),
                "reviewed": len(
                    (row.get("structured_review") or {}).get("reviewed_episode_ids")
                    or []
                ),
                "structured_status": (row.get("structured_review") or {}).get("status"),
                "attempts_succeeded": (
                    row.get("structured_review") or {}
                ).get("attempts_succeeded"),
                "attempts_failed": (row.get("structured_review") or {}).get(
                    "attempts_failed"
                ),
                "published_count": (
                    row.get("structured_review") or {}
                ).get("publish", {}).get("published_count"),
                "cards_applied": (
                    row.get("structured_review") or {}
                ).get("cards", {}).get("applied"),
            }
            for row in report["dates"]
        ],
    }
    print(json.dumps(sanitized, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
