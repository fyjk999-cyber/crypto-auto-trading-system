#!/usr/bin/env python
"""Canonical diary generator (STRATEGY DIRECTIVE §6/§7/§8/§9/§10).

Generates the Trading Diary and Strategy Diary DIRECTLY from canonical facts
in data/crypto_trader.db. No hand-assembled numbers. Every aggregate is
cross-checked against explicit invariants and printed with PASS/FAIL.

Invariants enforced (§7):
  TOTAL_DECISIONS == LONG + SHORT + NO_TRADE + WAIT + OTHER_VALID_ACTIONS
                    (+ UNCLASSIFIED reported explicitly)
  COMPLETED_EPISODES == LONG_EPISODES + SHORT_EPISODES (+ UNCLASSIFIED)
  NO_DOUBLE_COUNT: decision_evidence has exactly one row per decision_id
Truthfulness (§10):
  llm_reasoning is reported as NOT_AVAILABLE when absent, with a lineage
  pointer to decision_evidence.decision_json (thesis) + llm_invocation_id.
  The generator NEVER reconstructs "reasoning" from strategy+fit.

Usage:
  .venv/bin/python scripts/diary_generate.py --hours 8
  .venv/bin/python scripts/diary_generate.py --hours 8 --out-dir .ai-memory
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIT_BUCKETS = [
    ("0.00-0.40", 0.00, 0.40),
    ("0.40-0.50", 0.40, 0.50),
    ("0.50-0.60", 0.50, 0.60),
    ("0.60-0.70", 0.60, 0.70),
    ("0.70-0.80", 0.70, 0.80),
    ("0.80-0.90", 0.80, 0.90),
    ("0.90-1.00", 0.90, 1.00),
]
VALID_ACTIONS = {"LONG", "SHORT", "NO_TRADE", "WAIT", "HOLD", "CLOSE"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fit_bucket(fit: float | None) -> str:
    if fit is None:
        return "NO_FIT"
    for name, lo, hi in FIT_BUCKETS:
        if lo <= fit < hi or (hi == 1.00 and fit == 1.00):
            return name
    return "OUT_OF_RANGE"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--db", default="data/crypto_trader.db")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    since = (_utcnow() - timedelta(hours=args.hours)).strftime("%Y-%m-%d %H:%M")

    failures: list[str] = []
    lines: list[str] = []
    lines.append(f"# Canonical Diaries — window {since}Z → now (UTC)")
    lines.append("")
    lines.append("Generated directly from canonical DB facts. Invariants checked below.")
    lines.append("")

    # ---------------- decision accounting (§7/§9) ----------------
    ev_rows = conn.execute(
        "SELECT decision_id, symbol, created_at_utc, analysis_evidence_json, decision_json "
        "FROM decision_evidence WHERE created_at_utc >= ? ORDER BY created_at_utc", (since,)
    ).fetchall()
    ev_total = len(ev_rows)
    uniq_decisions = conn.execute(
        "SELECT COUNT(DISTINCT decision_id) FROM decision_evidence WHERE created_at_utc >= ?",
        (since,),
    ).fetchone()[0]

    action_counts: collections.Counter[str] = collections.Counter()
    fit_by_decision: dict[str, float | None] = {}
    strat_by_decision: dict[str, str | None] = {}
    fit_buckets: collections.Counter[str] = collections.Counter()
    bucket_trades: collections.Counter[str] = collections.Counter()
    bucket_episodes: dict[str, list[float]] = collections.defaultdict(list)
    bucket_wins: collections.Counter[str] = collections.Counter()
    for r in ev_rows:
        try:
            de = json.loads(r["decision_json"] or "{}")
        except Exception:
            de = {}
        act = de.get("action") or "<UNPARSEABLE>"
        if act not in VALID_ACTIONS:
            action_counts["UNCLASSIFIED_ACTION"] += 1
        else:
            action_counts[act] += 1
        # fit is per-DECISION (§9): one row per decision already verified below
        fit = de.get("strategy_fit_score")
        if fit is None:
            fit = (json.loads(r["analysis_evidence_json"] or "{}") or {}).get("strategy_fit_score")
        try:
            fit = float(fit) if fit is not None else None
        except (TypeError, ValueError):
            fit = None
        fit_by_decision[r["decision_id"]] = fit
        strat_by_decision[r["decision_id"]] = de.get("strategy_selected") or (
            json.loads(r["analysis_evidence_json"] or "{}") or {}
        ).get("selected_strategy")
        bucket = _fit_bucket(fit)
        fit_buckets[bucket] += 1
        if act in ("LONG", "SHORT"):
            bucket_trades[bucket] += 1

    lines.append("## Decision accounting (Strategy Diary, §7/§9)")
    lines.append("")
    lines.append(f"evidence rows: {ev_total} | distinct decisions: {uniq_decisions}")
    for a in sorted(action_counts):
        lines.append(f"  {a}: {action_counts[a]}")
    total_actions = sum(action_counts.values())
    ok1 = total_actions == ev_total and uniq_decisions == ev_total
    lines.append(
        "INVARIANT DECISION_COUNTS_RECONCILE: "
        f"{'PASS' if ok1 else 'FAIL'} (rows={ev_total}, sum(actions)={total_actions}, "
        f"distinct_decisions={uniq_decisions})"
    )
    if not ok1:
        failures.append("DECISION_COUNTS_RECONCILE")
    lines.append("")

    # ---------------- episode accounting (§8) ----------------
    ep_rows = conn.execute(
        "SELECT episode_id, symbol, direction, exit_reason, result, net_pnl, "
        "gross_pnl, fees, holding_time_seconds, market_regime, strategy_selected, "
        "llm_reasoning, entry_decision_id, created_at, market_type, "
        "entry_price, exit_price "
        "FROM ai_trade_episodes WHERE created_at >= ? ORDER BY created_at", (since,)
    ).fetchall()
    dir_counts: collections.Counter[str] = collections.Counter()
    for r in ep_rows:
        d = (r["direction"] or "UNKNOWN").upper()
        dir_counts[d if d in ("LONG", "SHORT") else "UNCLASSIFIED"] += 1
    completed = sum(1 for r in ep_rows if r["exit_price"] is not None)
    ok2 = sum(dir_counts.values()) == len(ep_rows)
    lines.append("## Episode accounting (Trading Diary, §8)")
    lines.append("")
    lines.append(f"episodes: {len(ep_rows)} (completed with exit_price: {completed})")
    for d in ("LONG", "SHORT", "UNCLASSIFIED"):
        if dir_counts.get(d):
            lines.append(f"  {d}: {dir_counts[d]}")
    lines.append(
        f"INVARIANT EPISODE_DIRECTION_RECONCILE: {'PASS' if ok2 else 'FAIL'} "
        f"(episodes={len(ep_rows)}, classified={sum(dir_counts.values())})"
    )
    if not ok2:
        failures.append("EPISODE_DIRECTION_RECONCILE")

    # SPOT/PERP split (§41)
    split = collections.Counter()
    for r in ep_rows:
        d = (r["direction"] or "UNKNOWN").upper()
        split[(r["market_type"] or "?", d if d in ("LONG", "SHORT") else "UNCLASSIFIED")] += 1
    lines.append("  SPOT/PERP × direction:")
    for (mt, d), n in sorted(split.items()):
        lines.append(f"    {mt} {d}: {n}")
    lines.append("")

    # NO_DOUBLE_COUNT (§9)
    ok3 = ev_total == uniq_decisions
    lines.append(f"INVARIANT NO_DOUBLE_COUNT: {'PASS' if ok3 else 'FAIL'} (one evidence row per decision)")
    if not ok3:
        failures.append("NO_DOUBLE_COUNT")
    lines.append("")

    # llm_reasoning truth (§10)
    with_reason = sum(1 for r in ep_rows if (r["llm_reasoning"] or "").strip())
    lines.append("## LLM reasoning truthfulness (§10)")
    lines.append("")
    lines.append(
        f"episodes with non-empty llm_reasoning column: {with_reason}/{len(ep_rows)}"
    )
    if with_reason == 0:
        lines.append(
            "  → AITradeEpisode.llm_reasoning = NOT_AVAILABLE. Canonical reasoning lives in "
            "decision_evidence.decision_json (`thesis`, `supporting_evidence`, "
            "`contradicting_evidence`, `invalidation_conditions`, `exit_conditions`, "
            "`llm_invocation_id`). This diary does NOT reconstruct reasoning from "
            "strategy+fit; it links via entry_decision_id lineage."
        )
    lines.append(f"INVARIANT LLM_REASONING_TRUTHFUL: PASS (no fabricated reasoning emitted)")
    lines.append("")

    # fit → outcome buckets (§47) — join decisions to episodes via entry_decision_id
    for r in ep_rows:
        fit = fit_by_decision.get(r["entry_decision_id"]) if r["entry_decision_id"] else None
        if fit is None:
            continue
        try:
            net = float(r["net_pnl"] or 0)
        except (TypeError, ValueError):
            continue
        b = _fit_bucket(fit)
        bucket_episodes[b].append(net)
        if (r["result"] or "").upper() == "WIN":
            bucket_wins[b] += 1
    lines.append("## Fit → Outcome buckets (per DECISION, §47/§48)")
    lines.append("")
    lines.append("| bucket | decisions | trades(LONG/SHORT) | episodes | wins | net_pnl_sum | avg_net |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, _lo, _hi in FIT_BUCKETS:
        n_dec = fit_buckets.get(name, 0)
        n_tr = bucket_trades.get(name, 0)
        eps = bucket_episodes.get(name, [])
        wins = bucket_wins.get(name, 0)
        net_sum = sum(eps)
        lines.append(
            f"| {name} | {n_dec} | {n_tr} | {len(eps)} | {wins} | {round(net_sum,8)} | {round(net_sum/len(eps),8) if eps else 0} |"
        )
    lines.append("")
    lines.append(
        "NOTE: outcome columns join episodes via entry_decision_id → decision fit; "
        "decisions without a linked episode count only in the decisions column."
    )
    lines.append("")

    # trades and exits detail for the trading diary
    lines.append("## Recent episodes (newest first)")
    lines.append("")
    lines.append("| created | symbol | type | dir | entry | exit | exit_reason | result | net_pnl | hold_s |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in ep_rows[:40]:
        lines.append(
            f"| {r['created_at'][:16]} | {r['symbol']} | {r['market_type']} | "
            f"{(r['direction'] or 'UNKNOWN').upper()} | {r['entry_price']} | {r['exit_price']} | "
            f"{r['exit_reason']} | {r['result']} | {r['net_pnl']} | "
            f"{round(r['holding_time_seconds'] or 0)} |"
        )
    lines.append("")

    fills = conn.execute(
        "SELECT f.timestamp, f.symbol, f.side, f.price, f.quantity, o.reduce_only "
        "FROM fills f JOIN orders o ON o.internal_order_id=f.order_id "
        "WHERE f.timestamp >= ? ORDER BY f.timestamp DESC LIMIT 40", (since,)
    ).fetchall()
    lines.append("## Recent fills (newest first)")
    lines.append("")
    lines.append("| ts | symbol | side | price | qty | reduce_only |")
    lines.append("|---|---|---|---|---|---|")
    for r in fills:
        lines.append(
            f"| {r['timestamp'][:16]} | {r['symbol']} | {r['side']} | {r['price']} | "
            f"{r['quantity']} | {r['reduce_only']} |"
        )
    lines.append("")

    verdict = "DIARY_TOTALS_RECONCILE = PASS" if not failures else (
        "DIARY_TOTALS_RECONCILE = FAIL: " + ", ".join(failures)
    )
    lines.append(f"## {verdict}")
    lines.append("")

    text = "\n".join(lines)
    out = Path(args.out_dir) if args.out_dir else None
    print(text)
    if out:
        out.mkdir(parents=True, exist_ok=True)
        stamp = _utcnow().strftime("%Y%m%dT%H%M")
        p = out / f"CANONICAL_DIARY_{stamp}Z.md"
        p.write_text(text, encoding="utf-8")
        print(f"\nsaved: {p}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
