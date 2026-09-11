#!/usr/bin/env python3
"""Read-only paper-trading review dossier.

Builds a factual, traceable dossier over previously generated PAPER orders,
fills, plans and factual episodes so the in-system Daily Review / structured
review path can consume it.  This script NEVER writes to a source database:
it opens each source with ``mode=ro`` + ``PRAGMA query_only=ON`` and takes a
consistent SQLite backup snapshot into a private temp directory.

Output is written to an explicit output directory (default
``.ops-growth-v2/paper_review``) and is safe to keep as evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation


def _iso(value) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Snapshot:
    def __init__(self, path: str) -> None:
        self.path = path
        self._holder = tempfile.TemporaryDirectory(prefix="paper-review-snapshot-")
        destination = os.path.join(self._holder.name, "snapshot.db")
        source = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15.0)
        source.execute("PRAGMA query_only=ON")
        target = sqlite3.connect(destination)
        source.backup(target)
        target.close()
        source.close()
        self.connection = sqlite3.connect(destination)
        self.connection.row_factory = sqlite3.Row

    def close(self) -> None:
        self.connection.close()
        self._holder.cleanup()

    def tables(self) -> set[str]:
        return {
            row[0]
            for row in self.connection.execute(
                "select name from sqlite_master where type='table'"
            )
        }

    def scalar(self, sql: str, default=None, params: tuple = ()):
        try:
            row = self.connection.execute(sql, params).fetchone()
            return row[0] if row is not None else default
        except sqlite3.Error:
            return default

    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        try:
            return [dict(row) for row in self.connection.execute(sql, params)]
        except sqlite3.Error:
            return []


def _snapshot_identity(path: str) -> dict:
    def digest(file_path: str) -> str | None:
        try:
            h = hashlib.sha256()
            with open(file_path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()
        except FileNotFoundError:
            return None

    stat = os.stat(path)
    return {
        "path": path,
        "size_bytes": stat.st_size,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        "sha256_main_at_read": digest(path),
        "wal_present": os.path.exists(path + "-wal"),
        "wal_size_bytes": os.path.getsize(path + "-wal")
        if os.path.exists(path + "-wal")
        else 0,
        "snapshot_method": "sqlite_backup_api_from_readonly_connection",
    }


def _orders_report(snapshot: Snapshot) -> dict:
    if "orders" not in snapshot.tables():
        return {"table": False}
    return {
        "table": True,
        "total": snapshot.scalar("select count(*) from orders", 0),
        "by_status": {
            row["status"]: row["count"]
            for row in snapshot.rows(
                "select status, count(*) as count from orders group by status"
            )
        },
        "by_mode": {
            row["trading_mode"]: row["count"]
            for row in snapshot.rows(
                "select trading_mode, count(*) as count from orders group by trading_mode"
            )
        },
        "min_created_at": snapshot.scalar("select min(created_at) from orders"),
        "max_created_at": snapshot.scalar("select max(created_at) from orders"),
        "filled_quantity_sum": _iso(
            snapshot.scalar("select sum(filled_quantity) from orders", 0)
        ),
        "symbols": snapshot.scalar("select count(distinct symbol) from orders", 0),
    }


def _fills_report(snapshot: Snapshot) -> dict:
    if "fills" not in snapshot.tables():
        return {"table": False}
    return {
        "table": True,
        "total": snapshot.scalar("select count(*) from fills", 0),
        "distinct_orders": snapshot.scalar(
            "select count(distinct order_id) from fills"
        ),
        "distinct_symbols": snapshot.scalar(
            "select count(distinct symbol) from fills"
        ),
        "fee_sum": _iso(snapshot.scalar("select sum(fee) from fills", 0)),
        "min_timestamp": snapshot.scalar("select min(timestamp) from fills"),
        "max_timestamp": snapshot.scalar("select max(timestamp) from fills"),
    }


def _plans_report(snapshot: Snapshot) -> dict:
    if "trade_plans" not in snapshot.tables():
        return {"table": False}
    return {
        "table": True,
        "total": snapshot.scalar("select count(*) from trade_plans", 0),
        "by_state": {
            row["state"]: row["count"]
            for row in snapshot.rows(
                "select state, count(*) as count from trade_plans group by state"
            )
        },
        "terminal_reasons": snapshot.rows(
            "select terminal_reason, count(*) as count from trade_plans "
            "where terminal_reason is not null group by terminal_reason "
            "order by count(*) desc limit 20"
        ),
    }


def _factual_episodes_report(snapshot: Snapshot) -> dict:
    if "trade_episodes" not in snapshot.tables():
        return {"table": False, "eligible": 0, "episodes": []}
    episodes = snapshot.rows(
        "select * from trade_episodes order by closed_at asc"
    )
    status_counts: dict[str, int] = {}
    per_day: dict[str, dict] = {}
    per_symbol: dict[str, dict] = {}
    per_direction: dict[str, dict] = {}
    wins = losses = breakeven = 0
    net_total = Decimal("0")
    gross_total = Decimal("0")
    fee_total = Decimal("0")
    funding_total = Decimal("0")
    review_episode_ids = set()
    if "ai_trade_reviews" in snapshot.tables():
        review_episode_ids = {
            row["episode_id"]
            for row in snapshot.rows("select episode_id from ai_trade_reviews")
        }
    decision_rows = {}
    if "llm_decisions" in snapshot.tables():
        decision_rows = {
            row["decision_id"]: row
            for row in snapshot.rows(
                "select decision_id, action, thesis, market_regime, "
                "supporting_evidence_json, contradicting_evidence_json, "
                "tool_refs_json, memory_refs_json, episode_refs_json, "
                "created_at from llm_decisions"
            )
        }
    coverage_by_key: dict[str, list[str]] = {}
    if "funding_coverage" in snapshot.tables():
        for row in snapshot.rows("select * from funding_coverage"):
            key = str(row.get("instrument_id") or row.get("symbol") or "")
            coverage_by_key.setdefault(key, []).append(
                str(row.get("status") or row.get("state") or "UNKNOWN")
            )

    queue: list[dict] = []
    for row in episodes:
        status = str(row.get("review_status") or "PENDING")
        status_counts[status] = status_counts.get(status, 0) + 1
        net = _dec(row.get("net_pnl")) or Decimal("0")
        gross = _dec(row.get("gross_pnl")) or Decimal("0")
        fees = _dec(row.get("fees")) or Decimal("0")
        funding = _dec(row.get("funding_pnl")) or Decimal("0")
        net_total += net
        gross_total += gross
        fee_total += fees
        funding_total += funding
        if net > 0:
            wins += 1
        elif net < 0:
            losses += 1
        else:
            breakeven += 1
        closed = str(row.get("closed_at") or "")[:10]
        per_day.setdefault(closed, {"count": 0, "net": Decimal("0")})
        per_day[closed]["count"] += 1
        per_day[closed]["net"] += net
        symbol = str(row.get("symbol") or "UNKNOWN")
        per_symbol.setdefault(
            symbol, {"count": 0, "net": Decimal("0"), "win": 0, "loss": 0}
        )
        per_symbol[symbol]["count"] += 1
        per_symbol[symbol]["net"] += net
        if net > 0:
            per_symbol[symbol]["win"] += 1
        elif net < 0:
            per_symbol[symbol]["loss"] += 1
        direction = str(row.get("direction") or "UNKNOWN")
        per_direction.setdefault(
            direction, {"count": 0, "net": Decimal("0"), "win": 0, "loss": 0}
        )
        per_direction[direction]["count"] += 1
        per_direction[direction]["net"] += net
        if net > 0:
            per_direction[direction]["win"] += 1
        elif net < 0:
            per_direction[direction]["loss"] += 1

        entry_decision = decision_rows.get(str(row.get("entry_decision_id") or ""))
        refs = {
            "position_decision_ids": row.get("position_decision_ids_json") or [],
            "risk_decision_ids": row.get("risk_decision_ids_json") or [],
            "order_ids": row.get("order_ids_json") or [],
            "fill_ids": row.get("fill_ids_json") or [],
        }
        coverage = coverage_by_key.get(symbol) or []
        missing: list[str] = []
        if not row.get("exit_decision_id"):
            missing.append("EXIT_DECISION_ID_MISSING")
        if not refs["fill_ids"]:
            missing.append("FILL_LINEAGE_MISSING")
        if not refs["order_ids"]:
            missing.append("ORDER_LINEAGE_MISSING")
        if not entry_decision or not str(entry_decision.get("thesis") or "").strip():
            missing.append("ENTRY_THESIS_MISSING")
        if "funding_coverage" in snapshot.tables() and not coverage:
            missing.append("FUNDING_COVERAGE_UNKNOWN")
        if any(value == "UNKNOWN" for value in coverage):
            missing.append("FUNDING_COVERAGE_UNKNOWN")
        review_row_present = str(row.get("episode_id") or "") in review_episode_ids
        if not review_row_present:
            missing.append("STRUCTURED_REVIEW_MISSING")
        queue.append(
            {
                "episode_id": row.get("episode_id"),
                "trade_plan_id": row.get("trade_plan_id"),
                "symbol": symbol,
                "direction": direction,
                "closed_at": _iso(row.get("closed_at")),
                "opened_at": _iso(row.get("opened_at")),
                "gross_pnl": _iso(gross),
                "fees": _iso(fees),
                "funding_pnl": _iso(funding),
                "net_pnl": _iso(net),
                "terminal_reason": row.get("terminal_reason"),
                "review_status": status,
                "entry_decision_id": row.get("entry_decision_id"),
                "exit_decision_id": row.get("exit_decision_id"),
                "entry_decision_thesis": (
                    str(entry_decision.get("thesis") or "")[:500]
                    if entry_decision
                    else None
                ),
                "entry_action": entry_decision.get("action") if entry_decision else None,
                "entry_regime": (
                    entry_decision.get("market_regime") if entry_decision else None
                ),
                "tool_ref_count": len(
                    (entry_decision.get("tool_refs_json") or [])
                    if entry_decision
                    else []
                ),
                "memory_ref_count": len(
                    (entry_decision.get("memory_refs_json") or [])
                    if entry_decision
                    else []
                ),
                "order_ref_count": len(refs["order_ids"]),
                "fill_ref_count": len(refs["fill_ids"]),
                "risk_decision_ref_count": len(refs["risk_decision_ids"]),
                "missing_evidence": missing,
                "review_eligible": not missing,
            }
        )
    return {
        "table": True,
        "total": len(episodes),
        "review_status_counts": status_counts,
        "net_total": _iso(net_total),
        "gross_total": _iso(gross_total),
        "fee_total": _iso(fee_total),
        "funding_total": _iso(funding_total),
        "win_count": wins,
        "loss_count": losses,
        "breakeven_count": breakeven,
        "min_closed_at": snapshot.scalar(
            "select min(closed_at) from trade_episodes"
        ),
        "max_closed_at": snapshot.scalar(
            "select max(closed_at) from trade_episodes"
        ),
        "per_day": {
            day: {"count": value["count"], "net": _iso(value["net"])}
            for day, value in sorted(per_day.items())
        },
        "per_symbol": {
            symbol: {
                "count": value["count"],
                "net": _iso(value["net"]),
                "win": value["win"],
                "loss": value["loss"],
            }
            for symbol, value in sorted(
                per_symbol.items(), key=lambda item: item[1]["count"], reverse=True
            )
        },
        "per_direction": {
            direction: {
                "count": value["count"],
                "net": _iso(value["net"]),
                "win": value["win"],
                "loss": value["loss"],
            }
            for direction, value in per_direction.items()
        },
        "review_eligible": sum(1 for item in queue if item["review_eligible"]),
        "review_pending": sum(
            1
            for item in queue
            if item["review_status"] == "PENDING" and item["review_eligible"]
        ),
        "episodes": queue,
    }


def _legacy_episodes_report(snapshot: Snapshot) -> dict:
    if "ai_trade_episodes" not in snapshot.tables():
        return {"table": False}
    rows = snapshot.rows("select * from ai_trade_episodes")
    results: dict[str, int] = {}
    total = Decimal("0")
    for row in rows:
        result = str(row.get("result") or "UNKNOWN")
        results[result] = results.get(result, 0) + 1
        value = _dec(row.get("pnl"))
        if value is not None:
            total += value
    return {
        "table": True,
        "total": len(rows),
        "result_counts": results,
        "pnl_sum": _iso(total),
        "canonical_factual": False,
        "disposition": "LEGACY_OBSERVATION / no canonical ledger lineage",
    }


def _decisions_report(snapshot: Snapshot) -> dict:
    if "llm_decisions" not in snapshot.tables():
        return {"table": False}
    return {
        "table": True,
        "total": snapshot.scalar("select count(*) from llm_decisions", 0),
        "min_created_at": snapshot.scalar("select min(created_at) from llm_decisions"),
        "max_created_at": snapshot.scalar("select max(created_at) from llm_decisions"),
        "by_action": {
            row["action"]: row["count"]
            for row in snapshot.rows(
                "select action, count(*) as count from llm_decisions "
                "group by action order by count(*) desc limit 20"
            )
        },
        "with_thesis": snapshot.scalar(
            "select count(*) from llm_decisions where thesis is not null "
            "and length(trim(thesis)) > 0",
            0,
        ),
    }


def build_dossier(label: str, path: str) -> dict:
    snapshot = Snapshot(path)
    try:
        tables = sorted(snapshot.tables())
        report = {
            "label": label,
            "identity": _snapshot_identity(path),
            "alembic_revision": snapshot.scalar(
                "select version_num from alembic_version limit 1"
            ),
            "table_count": len(tables),
            "orders": _orders_report(snapshot),
            "fills": _fills_report(snapshot),
            "trade_plans": _plans_report(snapshot),
            "factual_episodes": _factual_episodes_report(snapshot),
            "legacy_ai_episodes": _legacy_episodes_report(snapshot),
            "llm_decisions": _decisions_report(snapshot),
            "structured_reviews": {
                "ai_trade_reviews": snapshot.scalar(
                    "select count(*) from ai_trade_reviews", 0
                )
                if "ai_trade_reviews" in tables
                else None,
                "growth_review_attempts": snapshot.scalar(
                    "select count(*) from growth_review_attempts", 0
                )
                if "growth_review_attempts" in tables
                else None,
            },
        }
        return report
    finally:
        snapshot.close()


def _markdown(dossier: dict) -> str:
    lines = [
        f"# Paper trading review dossier — {dossier['label']}",
        "",
        f"- path: `{dossier['identity']['path']}`",
        f"- sha256(main at read): `{dossier['identity']['sha256_main_at_read']}`",
        f"- schema revision: `{dossier['alembic_revision']}`",
        "",
        "## Orders / fills / plans",
        f"- orders: {dossier['orders'].get('total', 'n/a')} "
        f"statuses={dossier['orders'].get('by_status')}",
        f"- fills: {dossier['fills'].get('total', 'n/a')} "
        f"fee_sum={dossier['fills'].get('fee_sum')}",
        f"- trade_plans: {dossier['trade_plans'].get('total', 'n/a')} "
        f"states={dossier['trade_plans'].get('by_state')}",
        "",
        "## Factual episodes",
    ]
    episodes = dossier["factual_episodes"]
    if not episodes.get("table"):
        lines.append("- no canonical `trade_episodes` table")
    else:
        lines.extend(
            [
                f"- total: {episodes['total']}",
                f"- status: {episodes['review_status_counts']}",
                f"- net total: {episodes['net_total']} "
                f"(gross {episodes['gross_total']}, fees {episodes['fee_total']}, "
                f"funding {episodes['funding_total']})",
                f"- win/loss/breakeven: {episodes['win_count']}/"
                f"{episodes['loss_count']}/{episodes['breakeven_count']}",
                f"- review eligible: {episodes['review_eligible']}, "
                f"pending+eligible: {episodes['review_pending']}",
                f"- closed range: {episodes['min_closed_at']} .. "
                f"{episodes['max_closed_at']}",
                "",
                "| day | count | net |",
                "| --- | ---: | ---: |",
            ]
        )
        for day, value in episodes["per_day"].items():
            lines.append(f"| {day} | {value['count']} | {value['net']} |")
        lines.append("")
        lines.append("| symbol | count | net | win | loss |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for symbol, value in episodes["per_symbol"].items():
            lines.append(
                f"| {symbol} | {value['count']} | {value['net']} | "
                f"{value['win']} | {value['loss']} |"
            )
        lines.append("")
        lines.append("### Review queue blockers")
        blockers: dict[str, int] = {}
        for item in episodes["episodes"]:
            for reason in item["missing_evidence"]:
                blockers[reason] = blockers.get(reason, 0) + 1
        for reason, count in sorted(blockers.items(), key=lambda x: -x[1]):
            lines.append(f"- {reason}: {count}")
    legacy = dossier["legacy_ai_episodes"]
    if legacy.get("table"):
        lines.extend(
            [
                "",
                "## Legacy AI episodes (not canonical factual)",
                f"- total: {legacy['total']} results={legacy['result_counts']}",
                f"- disposition: {legacy['disposition']}",
            ]
        )
    decisions = dossier["llm_decisions"]
    if decisions.get("table"):
        lines.extend(
            [
                "",
                "## LLM decisions",
                f"- total: {decisions['total']} with thesis: "
                f"{decisions['with_thesis']}",
                f"- range: {decisions['min_created_at']} .. "
                f"{decisions['max_created_at']}",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", action="append", required=True, metavar="LABEL=PATH")
    parser.add_argument("--out", default=".ops-growth-v2/paper_review")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    combined = {
        "generated_at": datetime.now(UTC).isoformat(),
        "note": (
            "Read-only dossier. No production DB write, no fake episode/fill, "
            "no harness-authored review lesson. Structured review must run "
            "inside the system with an approved provider."
        ),
        "databases": [],
    }
    for entry in args.db:
        label, _, path = entry.partition("=")
        if not path or not os.path.exists(path):
            combined["databases"].append(
                {"label": label, "path": path, "exists": False}
            )
            continue
        dossier = build_dossier(label, os.path.abspath(path))
        combined["databases"].append(dossier)
        markdown = _markdown(dossier)
        with open(
            os.path.join(args.out, f"{label}_DOSSIER.md"), "w", encoding="utf-8"
        ) as handle:
            handle.write(markdown)
    with open(
        os.path.join(args.out, "PAPER_REVIEW_DOSSIER.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump(combined, handle, indent=2, default=str)
    print(
        json.dumps(
            {
                "out": args.out,
                "databases": [
                    {
                        "label": item.get("label"),
                        "orders": item.get("orders", {}).get("total"),
                        "fills": item.get("fills", {}).get("total"),
                        "factual_episodes": item.get("factual_episodes", {}).get(
                            "total"
                        ),
                        "review_pending": item.get("factual_episodes", {}).get(
                            "review_pending"
                        ),
                    }
                    for item in combined["databases"]
                ],
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
