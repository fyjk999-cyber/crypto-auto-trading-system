#!/usr/bin/env python3
"""Freeze the decision-time daily Top-10 opportunities (Growth V2, Phase 5).

Reads the live runtime's real factor-scanner candidates and persists the first
freeze for the trading day (idempotent, no hindsight). Learning/observability
only: never submits an order.

Usage:
    python scripts/freeze_daily_top10.py --base-url http://127.0.0.1:8010 \
        --db /tmp/lr2-soak2/data/crypto_trader.db
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from crypto_trader.market_data.opportunity.daily_freeze import DailyOpportunityFreezer  # noqa: E402
from crypto_trader.persistence import Database  # noqa: E402


def fetch_candidates(base_url: str) -> list[dict]:
    url = base_url.rstrip("/") + "/opportunity/candidates"
    with urllib.request.urlopen(url, timeout=15) as response:  # noqa: S310
        payload = json.loads(response.read().decode())
    return list(payload.get("candidates") or [])


def to_frozen_candidate(candidate: dict) -> dict:
    """Map a live candidate to the freeze schema using only decision-time facts."""
    triggered = list(candidate.get("triggered") or [])
    strength = sum(float(item.get("strength") or 0.0) for item in triggered)
    return {
        "symbol": str(candidate.get("symbol") or ""),
        "score": float(candidate.get("factor_trigger_count") or 0) + strength / 1000.0,
        "candidate_source": str(candidate.get("source") or ""),
        "factor_evidence": [str(item.get("factor")) for item in triggered],
    }


async def freeze(base_url: str, db_path: Path, trading_day: str) -> dict:
    candidates = [to_frozen_candidate(item) for item in fetch_candidates(base_url)]
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    try:
        freezer = DailyOpportunityFreezer(database.session_factory)
        result = await freezer.freeze(trading_day, candidates)
    finally:
        await database.close()
    result["candidate_count"] = len(candidates)
    result["authority"] = "LEARNING_ONLY"
    result["not_an_order"] = True
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze daily Top-10 opportunities")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--db", default="/tmp/lr2-soak2/data/crypto_trader.db")
    parser.add_argument("--trading-day", default=None)
    args = parser.parse_args()
    day = args.trading_day or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    try:
        result = asyncio.run(freeze(args.base_url, Path(args.db), day))
    except (urllib.error.URLError, OSError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}", "trading_day": day}))
        raise SystemExit(1) from exc
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
