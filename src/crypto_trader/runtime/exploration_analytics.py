"""PAPER exploration experience analytics (read-only).

Aggregates DecisionEvidence (decisions, rejections, counterfactuals) and
order/fill history into learning coverage metrics:

- decision class distribution (NORMAL / EXPLORATION / NO_TRADE + reasons)
- strategy x regime coverage of decisions and executed entries
- completed-trade outcomes attributed via decision signal_id -> orders
  (client_order_id embeds the signal_id) -> fills
- confidence / fit-score buckets for later calibration (CORE_TRADING_DOCTRINE
  learning loop: outcomes are evidence, never direct truth)

No mutation, no fabrication: metrics derive only from persisted rows.
"""

from __future__ import annotations

import json
import statistics
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crypto_trader.config import Settings

_CHIEF_STRATEGY = "llm_chief_trader"


def is_valid_learning_sample(decision: dict | None) -> bool:
    """§5 mandatory lineage for a completed learning sample.

    A PAPER trade counts toward the 200-sample target only when its entry
    decision carries the full evidence lineage. Missing lineage does NOT
    block trading; it blocks contamination of later calibration.
    """
    if not decision:
        return False
    if not decision.get("factor_snapshot_id"):
        return False
    if not decision.get("factor_set_version"):
        return False
    if str(decision.get("market_regime", "")).upper() in ("", "UNKNOWN"):
        return False
    if not decision.get("selected_strategy"):
        return False
    if decision.get("strategy_fit_score") in (None, ""):
        return False
    if not decision.get("decision_class"):
        return False
    return True


def _bucket(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= 0.80:
        return "0.80+"
    if value >= 0.70:
        return "0.70-0.80"
    if value >= 0.60:
        return "0.60-0.70"
    if value >= 0.50:
        return "0.50-0.60"
    return "0.40-0.50"


def _summary(returns: list[float], holdings: list[float] | None = None) -> dict:
    if not returns:
        return {"trade_count": 0}
    wins = [n for n in returns if n > 0]
    losses = [n for n in returns if n < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    summary = {
        "trade_count": len(returns),
        "win_rate": round(len(wins) / len(returns), 4),
        "average_return": round(statistics.fmean(returns), 8),
        "median_return": round(statistics.median(returns), 8),
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss else None,
        "expectancy": round(statistics.fmean(returns), 8),
        "max_adverse_excursion": "NOT_AVAILABLE",
        "max_favorable_excursion": "NOT_AVAILABLE",
        "exit_reason": "NOT_AVAILABLE",
    }
    if holdings:
        summary["average_holding_seconds"] = round(statistics.fmean(holdings), 1)
    else:
        summary["average_holding_seconds"] = "NOT_AVAILABLE"
    return summary


def _bucket_summary(trades: list[dict], key: str) -> dict:
    out: dict[str, dict] = {}
    for trade in trades:
        bucket = _bucket(trade.get(key))
        out.setdefault(bucket, []).append(trade["return_rate"])
    return {bucket: _summary(values) for bucket, values in sorted(out.items())}


def _group_summary(trades: list[dict], key: str) -> dict:
    out: dict[str, list[dict]] = {}
    for trade in trades:
        out.setdefault(str(trade.get(key) or "UNKNOWN"), []).append(trade)
    grouped = {}
    for group, group_trades in sorted(out.items()):
        holdings = [
            t["holding_seconds"] for t in group_trades if t.get("holding_seconds")
        ]
        grouped[group] = _summary(
            [t["return_rate"] for t in group_trades], holdings
        )
        grouped[group]["strategy_fit_score"] = sorted(
            {str(t.get("strategy_fit_score")) for t in group_trades}
        )
        grouped[group]["decision_class"] = sorted(
            {str(t.get("decision_class")) for t in group_trades}
        )
    return grouped


def _signal_from_client(client_order_id: str) -> str:
    """Entry orders carry client_order_id = strategy_id + '_' + signal_id."""
    prefix = _CHIEF_STRATEGY + "_"
    if client_order_id.startswith(prefix):
        return client_order_id[len(prefix):]
    return ""


async def exploration_status(source: AsyncEngine | Any, settings: Settings) -> dict:
    """Read-only learning-coverage report for the exploration stage."""
    active = settings.exploration_mode_active
    policy = {
        "PAPER_EXPLORATION_MODE": active,
        "minimum_strategy_fit": (
            settings.exploration_min_fit if active else settings.live_min_strategy_fit
        ),
        "minimum_trade_confidence": (
            settings.exploration_min_confidence
            if active
            else settings.live_min_trade_confidence
        ),
        "exploration_probability": settings.exploration_probability,
        "exploration_position_size_fraction": settings.exploration_size_fraction,
        "normal_fit_threshold": settings.normal_fit_threshold,
        "normal_confidence_threshold": settings.normal_confidence_threshold,
        "entry_cooldown_seconds": settings.entry_cooldown_seconds,
        "exploration_max_holding_seconds": settings.exploration_max_holding_seconds,
        "sample_target": settings.exploration_sample_target,
        "stage": "STAGE_A_EXPLORATION" if active else "POLICY_INACTIVE",
    }

    async def _collect(conn: AsyncConnection):
        decision_rows = (
            await conn.execute(
                text(
                    "SELECT factor_snapshot_id, factor_set_version, decision_json, "
                    "analysis_evidence_json, execution_intent_reference "
                    "FROM decision_evidence WHERE strategy_id = :sid "
                    "ORDER BY created_at_utc ASC LIMIT 5000"
                ),
                {"sid": _CHIEF_STRATEGY},
            )
        ).fetchall()
        fill_rows = (
            await conn.execute(
                text(
                    "SELECT f.symbol, f.side, f.price, f.quantity, f.timestamp, "
                    "o.client_order_id FROM fills f JOIN orders o "
                    "ON o.internal_order_id = f.order_id ORDER BY f.timestamp ASC"
                )
            )
        ).fetchall()
        return decision_rows, fill_rows

    if isinstance(source, AsyncEngine):
        async with source.connect() as conn:
            rows, fill_rows = await _collect(conn)
    else:
        async with source() as session:
            conn = await session.connection()
            rows, fill_rows = await _collect(conn)

    decisions: list[dict] = []
    for snapshot_col, factor_set_col, decision_json, analysis_json, signal_ref in rows:
        analysis = json.loads(analysis_json or "{}")
        decision = json.loads(decision_json or "{}")
        decisions.append(
            {
                "decision_id": decision.get("decision_id", ""),
                "timestamp_utc": analysis.get("timestamp_utc", ""),
                "action": decision.get("action", ""),
                "decision_class": analysis.get("decision_class", ""),
                "reason_codes": decision.get("reason_codes", []),
                "selected_strategy": decision.get("selected_strategy", "")
                or analysis.get("selected_strategy", ""),
                "strategy_fit_score": decision.get("strategy_fit_score"),
                "market_regime": decision.get("market_regime", ""),
                "raw_confidence": decision.get("raw_llm_confidence"),
                "evidence_adjusted_confidence": decision.get(
                    "evidence_adjusted_confidence"
                ),
                "factor_snapshot_id": snapshot_col or "",
                "factor_set_version": factor_set_col or "",
                "signal_id": signal_ref or "",
            }
        )

    class_counts: dict[str, int] = {}
    regime_counts: dict[str, int] = {}
    strategy_counts: dict[str, int] = {}
    strategy_regime: dict[str, dict[str, int]] = {}
    rejection_reasons: dict[str, int] = {}
    signal_to_decision: dict[str, dict] = {}
    for row in decisions:
        reasons = row["reason_codes"] or []
        if row["action"] == "NO_TRADE":
            key = next((r for r in reasons if r != "ACTION_UNRECOGNIZED_FAIL_CLOSED"), "NO_TRADE")
            rejection_reasons[key] = rejection_reasons.get(key, 0) + 1
        cls = row["decision_class"] or row["action"] or "UNKNOWN"
        class_counts[cls] = class_counts.get(cls, 0) + 1
        regime = row["market_regime"] or "UNKNOWN"
        regime_counts[regime] = regime_counts.get(regime, 0) + 1
        if row["selected_strategy"]:
            strategy_counts[row["selected_strategy"]] = (
                strategy_counts.get(row["selected_strategy"], 0) + 1
            )
            strategy_regime.setdefault(row["selected_strategy"], {}).setdefault(
                regime, 0
            )
            strategy_regime[row["selected_strategy"]][regime] += 1
        if row["signal_id"]:
            signal_to_decision[row["signal_id"]] = row

    # Single-lot position accounting per symbol (§14: exploration never
    # pyramids, so one open lot per symbol is sufficient). Entries are the
    # fills that flip the net position toward the fill side; closes realize
    # the lot. Attribution: the entry fill's order client_order_id embeds the
    # decision signal_id.
    executed_entries = 0
    trades: list[dict] = []
    open_lot: dict[str, dict] = {}
    net: dict[str, float] = {}
    executed_strategy_counts: dict[str, int] = {}
    executed_regime_counts: dict[str, int] = {}
    executed_strategy_regime: dict[str, dict[str, int]] = {}
    for fill in fill_rows:
        symbol = str(fill.symbol)
        price = float(fill.price or 0)
        qty = float(fill.quantity or 0)
        if qty <= 0 or price <= 0:
            continue
        signed = qty if str(fill.side) == "BUY" else -qty
        previous = net.get(symbol, 0.0)
        current = previous + signed
        net[symbol] = current
        opens_entry = (previous == 0.0) or (previous > 0 and signed > 0) or (
            previous < 0 and signed < 0
        )
        if opens_entry:
            executed_entries += 1
            meta = signal_to_decision.get(
                _signal_from_client(str(fill.client_order_id or ""))
            )
            open_lot[symbol] = {
                "price": price,
                "qty": abs(signed),
                "ts": str(fill.timestamp),
                "side": str(fill.side),
                "direction": "LONG" if str(fill.side) == "BUY" else "SHORT",
                "fit": meta.get("strategy_fit_score") if meta else None,
                "confidence": (
                    meta.get("evidence_adjusted_confidence")
                    or meta.get("raw_confidence")
                )
                if meta
                else None,
                "strategy": meta.get("selected_strategy") if meta else None,
                "regime": meta.get("market_regime") if meta else None,
                "decision_class": meta.get("decision_class") if meta else None,
                "decision_id": meta.get("decision_id") if meta else None,
                "valid_sample": is_valid_learning_sample(meta),
            }
            executed_strategy = meta.get("selected_strategy") if meta else None
            executed_regime = meta.get("market_regime") if meta else None
            if executed_strategy:
                executed_strategy_counts[executed_strategy] = (
                    executed_strategy_counts.get(executed_strategy, 0) + 1
                )
                executed_strategy_regime.setdefault(
                    executed_strategy, {}
                ).setdefault(executed_regime or "UNKNOWN", 0)
                executed_strategy_regime[executed_strategy][
                    executed_regime or "UNKNOWN"
                ] += 1
            if executed_regime:
                executed_regime_counts[executed_regime] = (
                    executed_regime_counts.get(executed_regime, 0) + 1
                )
            continue
        lot = open_lot.pop(symbol, None)
        if lot is None:
            continue
        direction = 1.0 if lot["side"] == "BUY" else -1.0
        return_rate = direction * (price - lot["price"]) / lot["price"]
        holding_seconds: float | None = None
        try:
            from datetime import datetime as _dt

            entry_ts = _dt.fromisoformat(lot["ts"])
            exit_ts = _dt.fromisoformat(str(fill.timestamp))
            holding_seconds = (exit_ts - entry_ts).total_seconds()
        except (ValueError, TypeError):
            holding_seconds = None
        trades.append(
            {
                "symbol": symbol,
                "return_rate": return_rate,
                "holding_seconds": holding_seconds,
                "strategy_fit_score": lot["fit"],
                "evidence_adjusted_confidence": lot["confidence"],
                "selected_strategy": lot["strategy"],
                "market_regime": lot["regime"],
                "decision_class": lot["decision_class"],
                "decision_id": lot["decision_id"],
                "direction": lot.get("direction", ""),
                "valid_sample": lot.get("valid_sample", False),
            }
        )

    completed = len(trades)
    valid_completed = sum(1 for t in trades if t.get("valid_sample"))
    invalid_learning_samples = completed - valid_completed
    completed_strategy_counts: dict[str, int] = {}
    completed_regime_counts: dict[str, int] = {}
    completed_strategy_regime: dict[str, dict[str, int]] = {}
    for trade in trades:
        strategy = str(trade.get("selected_strategy") or "")
        regime = str(trade.get("market_regime") or "")
        if not strategy:
            continue
        completed_strategy_counts[strategy] = (
            completed_strategy_counts.get(strategy, 0) + 1
        )
        completed_strategy_regime.setdefault(strategy, {}).setdefault(
            regime, 0
        )
        completed_strategy_regime[strategy][regime] += 1
        if regime:
            completed_regime_counts[regime] = (
                completed_regime_counts.get(regime, 0) + 1
            )
    holdings = [t["holding_seconds"] for t in trades if t.get("holding_seconds")]
    overall = _summary([t["return_rate"] for t in trades], holdings)
    completed_long = sum(1 for t in trades if t.get("direction") == "LONG")
    completed_short = sum(1 for t in trades if t.get("direction") == "SHORT")
    normal_long = sum(
        1 for t in trades
        if t.get("direction") == "LONG" and t.get("decision_class") == "NORMAL_ENTRY"
    )
    normal_short = sum(
        1 for t in trades
        if t.get("direction") == "SHORT" and t.get("decision_class") == "NORMAL_ENTRY"
    )
    exploration_long = sum(
        1 for t in trades
        if t.get("direction") == "LONG"
        and t.get("decision_class") == "EXPLORATION_ENTRY"
    )
    exploration_short = sum(
        1 for t in trades
        if t.get("direction") == "SHORT"
        and t.get("decision_class") == "EXPLORATION_ENTRY"
    )
    progress = {
        "valid_completed_samples": valid_completed,
        "completed_samples": valid_completed,  # frontend/status backward-compat
        "completed_long": completed_long,
        "completed_short": completed_short,
        "normal_long": normal_long,
        "normal_short": normal_short,
        "exploration_long": exploration_long,
        "exploration_short": exploration_short,
        "sample_target": settings.exploration_sample_target,
        "target_reached": valid_completed >= settings.exploration_sample_target,
        "executed_entries": executed_entries,
        "total_decisions": len(decisions),
        "invalid_learning_samples": invalid_learning_samples,
        "rejected_opportunities": sum(rejection_reasons.values()),
        "rejection_reasons": rejection_reasons,
        "mae_mfe": "NOT_AVAILABLE (tick-level excursion tracking is future work)",
    }

    coverage = {
        "decision_coverage": {
            "decision_class_distribution": class_counts,
            "strategy_distribution": strategy_counts,
            "regime_distribution": regime_counts,
            "strategy_by_regime": strategy_regime,
        },
        "executed_trade_coverage": {
            "strategy_distribution": executed_strategy_counts,
            "regime_distribution": executed_regime_counts,
            "strategy_by_regime": executed_strategy_regime,
        },
        "completed_trade_coverage": {
            "strategy_distribution": completed_strategy_counts,
            "regime_distribution": completed_regime_counts,
            "strategy_by_regime": completed_strategy_regime,
        },
    }

    calibration = {
        "by_confidence_bucket": _bucket_summary(
            trades, "evidence_adjusted_confidence"
        ),
        "by_fit_bucket": _bucket_summary(trades, "strategy_fit_score"),
        "note": "buckets fill as completed PAPER trades accumulate; loss is not "
        "factor-bad / profit is not factor-good (CORE_TRADING_DOCTRINE_V1 "
        "learning loop)",
    }

    return {
        "policy": policy,
        "progress": progress,
        "coverage": coverage,
        "outcomes_overall": overall,
        "outcomes_by_strategy": _group_summary(trades, "selected_strategy"),
        "outcomes_by_regime": _group_summary(trades, "market_regime"),
        "outcomes_by_direction": _group_summary(trades, "direction"),
        "outcomes_by_decision_class": _group_summary(trades, "decision_class"),
        "calibration": calibration,
    }
