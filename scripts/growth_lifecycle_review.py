#!/usr/bin/env python3
"""Derive Growth V2 lifecycle reviews from a factual closed episode.

Reads the canonical DB only (orders/fills/decisions/audits), computes the factual
goodness of the exit from real fill prices, and writes the applicable review
taxonomy entries through the existing ``ai_trade_reviews`` write-through.

This is learning/observability only. It never trades, never alters Risk hard
rules, execution safety, model formulas or order authority, and it never invents
fills or decisions: every finding cites persisted IDs.

Usage:
    python scripts/growth_lifecycle_review.py --db /tmp/lr2-soak2/data/crypto_trader.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import asyncio  # noqa: E402

from crypto_trader.learning.growth_persistence import GrowthPersistence  # noqa: E402
from crypto_trader.learning.review_taxonomy import classify_review  # noqa: E402
from crypto_trader.persistence import Database  # noqa: E402


def _load(connection: sqlite3.Connection, query: str, **params):
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(query, params)]


def _vwap(fills: list[dict]) -> Decimal:
    total_qty = sum((Decimal(str(item["quantity"])) for item in fills), Decimal("0"))
    if total_qty == 0:
        return Decimal("0")
    notional = sum(
        (Decimal(str(item["price"])) * Decimal(str(item["quantity"])) for item in fills),
        Decimal("0"),
    )
    return notional / total_qty


def build_findings(db_path: Path, plan_id: str | None) -> tuple[str, list, dict]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        episodes = _load(
            connection, "SELECT * FROM trade_episodes ORDER BY created_at DESC LIMIT 1"
        )
        if not episodes:
            raise SystemExit("no closed trade episode found")
        episode = episodes[0]
        plan_id = plan_id or str(episode["trade_plan_id"])
        orders = [
            row
            for row in _load(connection, "SELECT * FROM orders")
            if (json.loads(row["metadata_json"] or "{}").get("trade_plan_id") == plan_id)
        ]
        order_ids = {row["internal_order_id"] for row in orders}
        fills = [
            row for row in _load(connection, "SELECT * FROM fills") if row["order_id"] in order_ids
        ]
        decisions = _load(
            connection,
            "SELECT * FROM llm_decisions WHERE symbol = :symbol ORDER BY created_at",
            symbol=episode["symbol"],
        )
        audits = _load(
            connection,
            "SELECT action, COUNT(*) c FROM audit_events GROUP BY action",
        )
    finally:
        connection.close()

    entry_fills = [fill for fill in fills if fill["side"] == "SELL"]
    exit_fills = [fill for fill in fills if fill["side"] == "BUY"]
    direction = str(episode.get("direction") or "SHORT").upper()
    if direction == "LONG":
        entry_fills, exit_fills = exit_fills, entry_fills
    entry_vwap = _vwap(entry_fills)
    exit_vwap = _vwap(exit_fills)
    if entry_vwap <= 0 or exit_vwap <= 0:
        net_bps = Decimal("0")
    else:
        move = (exit_vwap - entry_vwap) / entry_vwap * Decimal("10000")
        net_bps = move if direction == "LONG" else -move

    audit_counts = {row["action"]: row["c"] for row in audits}
    position_decisions = sum(
        1 for item in decisions if item["action"] in {"HOLD", "REDUCE", "EXIT"}
    )
    findings = []
    exit_review = classify_review(
        event_kind="MODIFY_EXIT",
        outcome_bps=float(net_bps),
        notes=(
            f"plan={plan_id} entry_vwap={entry_vwap} exit_vwap={exit_vwap} "
            f"fills={len(fills)} exit_decision={episode.get('exit_decision_id')}"
        ),
    )
    if exit_review:
        findings.append(exit_review)
    invocation_review = classify_review(
        event_kind="LLM_INVOCATION",
        outcome_bps=float(net_bps),
        notes=(
            f"position_decisions={position_decisions} "
            f"total_decisions={len(decisions)} "
            f"live_llm_position_audits={audit_counts.get('LIVE_LLM_POSITION_DECISION', 0)}"
        ),
    )
    if invocation_review:
        findings.append(invocation_review)
    if audit_counts.get("RISK_L2") or audit_counts.get("RISK_L1"):
        risk_review = classify_review(
            event_kind="RISK_L2" if audit_counts.get("RISK_L2") else "RISK_L1",
            outcome_bps=float(net_bps),
            notes="risk audit events present for lifecycle",
        )
        if risk_review:
            findings.append(risk_review)

    closed_at = str(episode.get("closed_at") or datetime.now(UTC).isoformat())
    trading_day = closed_at[:10]
    summary = {
        "plan_id": plan_id,
        "episode_id": episode.get("episode_id"),
        "symbol": episode.get("symbol"),
        "direction": direction,
        "entry_vwap": str(entry_vwap),
        "exit_vwap": str(exit_vwap),
        "net_bps": float(net_bps),
        "fills": len(fills),
        "review_types": [finding.review_type for finding in findings],
    }
    return trading_day, findings, summary


async def write_findings(db_path: Path, trading_day: str, findings: list) -> int:
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    try:
        writer = GrowthPersistence(database.session_factory)
        return await writer.write_reviews(trading_day=trading_day, findings=findings)
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Growth lifecycle review from facts")
    parser.add_argument("--db", default="/tmp/lr2-soak2/data/crypto_trader.db")
    parser.add_argument("--plan-id", default=None)
    args = parser.parse_args()
    trading_day, findings, summary = build_findings(Path(args.db), args.plan_id)
    written = asyncio.run(write_findings(Path(args.db), trading_day, findings))
    print(
        json.dumps(
            {
                "trading_day": trading_day,
                "summary": summary,
                "written": written,
                "verdicts": [f.verdict for f in findings],
                "authority": "LEARNING_ONLY",
                "is_order": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
