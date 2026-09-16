"""ML dataset collector for scanner cycles (Phase B).

The Market Scanner keeps its discovery responsibility; this collector adds two
derived responsibilities without creating a second source of truth:

1. Expert Feature Provider: freeze the decision-time features used by the
   25-model evidence layer.
2. ML Dataset Collector: persist SCAN_SNAPSHOT rows for candidates AND control
   samples so selection bias can be quantified later.

Derived/learning only: LEARNING_ONLY, is_order=False, no runtime authority.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from crypto_trader.domain.identifiers import new_id
from crypto_trader.persistence.models import ScanSnapshotORM

SCAN_FEATURE_VERSION = "scan-features-v1"
SCAN_SNAPSHOT_VERSION = "scan-snapshot-v1"
CONTROL_SAMPLING_METHOD = "STRATIFIED_RANDOM"


def decision_time_features(
    facts,
    *,
    model_evidence: list | None = None,
    costs=None,
    growth_context: dict | None = None,
) -> dict:
    """Freeze only information available at decision time (explicit flag)."""
    bid = getattr(facts, "bid", None)
    ask = getattr(facts, "ask", None)
    bid_qty = getattr(facts, "bid_qty", None)
    ask_qty = getattr(facts, "ask_qty", None)
    l1_imbalance = None
    if bid_qty is not None and ask_qty is not None and (bid_qty + ask_qty) > 0:
        l1_imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty)
    volume_24h = getattr(facts, "volume_24h_usd", None)
    cohort = getattr(facts, "cohort_median_turnover_usd", None)
    relative_volume = volume_24h / cohort if volume_24h and cohort and cohort > 0 else None
    evidence = []
    for item in model_evidence or []:
        evidence.append(
            {
                "model_id": getattr(item, "model_id", None),
                "direction": str(getattr(item, "direction", "")),
                "score": getattr(item, "score", None),
                "confidence": getattr(item, "confidence", None),
                "family": getattr(item, "family", None),
                "available": getattr(item, "available", None),
            }
        )
    cost_dict = None
    if costs is not None:
        cost_dict = (
            costs.model_dump()
            if hasattr(costs, "model_dump")
            else {k: getattr(costs, k, None) for k in ("total_cost_bps",)}
        )
    return {
        "feature_version": SCAN_FEATURE_VERSION,
        "available_at_decision_time": True,
        "observed_at": (
            getattr(facts, "observed_at", None).isoformat()
            if getattr(facts, "observed_at", None)
            else None
        ),
        "price": getattr(facts, "last_price", None),
        "best_bid": bid,
        "best_ask": ask,
        "spread_bps": getattr(facts, "spread_bps", None),
        "l1_imbalance": l1_imbalance,
        "l5_imbalance": getattr(facts, "book_imbalance_l5", None),
        "l10_imbalance": None,  # feed exposes L5 only; explicit quality gap
        "bid_qty": bid_qty,
        "ask_qty": ask_qty,
        "microprice": getattr(facts, "microprice", None),
        "trade_count": getattr(facts, "trade_count", None),
        "trade_notional_window_usd": getattr(facts, "trade_notional_window_usd", None),
        "large_trade_count": getattr(facts, "large_trade_count", None),
        "taker_buy_volume": getattr(facts, "taker_buy_volume", None),
        "taker_sell_volume": getattr(facts, "taker_sell_volume", None),
        "cvd": getattr(facts, "cvd", None),
        "relative_volume": relative_volume,
        "open_interest": getattr(facts, "open_interest", None),
        "oi_change_pct": getattr(facts, "oi_change_pct", None),
        "funding_rate": getattr(facts, "funding_rate", None),
        "basis_bps": None,  # not first-class in MarketState yet
        "price_change_24h_pct": getattr(facts, "price_change_24h_pct", None),
        "candle_count": len(getattr(facts, "candles", []) or []),
        "evidence_quality": getattr(facts, "evidence_quality", None),
        "evidence_degraded_reasons": list(getattr(facts, "evidence_degraded_reasons", []) or []),
        "model_evidence": evidence,
        "model_count": len(evidence),
        "costs": cost_dict,
        "growth_context": dict(growth_context or {}),
        "authority": "LEARNING_ONLY",
        "is_order": False,
    }


def build_scan_snapshot(
    *,
    symbol: str,
    features: dict,
    captured_at: datetime | None = None,
    cycle_id: str | None = None,
    candidate: bool,
    control: bool,
    scanner_rank: int | None = None,
    scanner_score: float | None = None,
    selection_reason: str = "",
    sampling_method: str = "",
    selection_probability: float | None = None,
    market_regime: str | None = None,
) -> dict:
    captured = captured_at or datetime.now(UTC)
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    canonical = json.dumps(features, sort_keys=True, default=str).encode()
    return {
        "snapshot_id": new_id("scan"),
        "captured_at": captured,
        "trading_day": captured.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "snapshot_version": SCAN_SNAPSHOT_VERSION,
        "snapshot_hash": hashlib.sha256(canonical).hexdigest(),
        "cycle_id": cycle_id or new_id("cycle"),
        "symbol": symbol,
        "candidate": bool(candidate),
        "control": bool(control),
        "scanner_rank": scanner_rank,
        "scanner_score": scanner_score,
        "selection_reason": selection_reason[:200],
        "sampling_method": sampling_method[:40],
        "selection_probability": selection_probability,
        "market_regime": market_regime,
        "features_json": features,
    }


def select_control_samples(
    facts_by_symbol: dict,
    *,
    candidate_symbols: set[str],
    count: int = 20,
    seed: int = 42,
    liquidity_tier_of=None,
) -> list[dict]:
    """Stratified-random control samples from eligible non-candidates."""
    eligible = sorted(symbol for symbol in facts_by_symbol if symbol not in candidate_symbols)
    if not eligible or count <= 0:
        return []
    rng = random.Random(seed)
    tiers: dict[str, list[str]] = {}
    for symbol in eligible:
        tier = str(liquidity_tier_of(symbol)) if callable(liquidity_tier_of) else "ALL"
        tiers.setdefault(tier, []).append(symbol)
    chosen: list[str] = []
    tier_names = sorted(tiers)
    for index in range(count):
        non_empty = [tier for tier in tier_names if tiers[tier]]
        if not non_empty:
            break
        tier = non_empty[index % len(non_empty)]
        chosen.append(tiers[tier].pop(rng.randrange(len(tiers[tier]))))
    probability = min(1.0, count / max(1, len(eligible)))
    return [
        {
            "symbol": symbol,
            "candidate": False,
            "control": True,
            "scanner_rank": None,
            "scanner_score": None,
            "selection_reason": "CONTROL_SAMPLE",
            "sampling_method": CONTROL_SAMPLING_METHOD,
            "selection_probability": probability,
        }
        for symbol in chosen
    ]


class ScanSnapshotCollector:
    authority = "LEARNING_ONLY"
    is_order = False

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def persist(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        written = 0
        async with self._session_factory() as session:
            existing = {
                row[0]
                for row in (
                    await session.execute(
                        select(ScanSnapshotORM.snapshot_id).where(
                            ScanSnapshotORM.snapshot_id.in_([row["snapshot_id"] for row in rows])
                        )
                    )
                ).all()
            }
            for row in rows:
                if row["snapshot_id"] in existing:
                    continue
                session.add(ScanSnapshotORM(**row))
                written += 1
            await session.commit()
        return written
