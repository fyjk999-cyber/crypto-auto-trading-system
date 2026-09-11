"""Bounded research candidate pool (§7.1).

Composition target for the ChiefTrader market-selection call:

    up to 10 factor candidates        (factor nomination — attention only)
    up to 10 fair-rotation markets    (oldest LLM-research exposure first)
    up to 10 active / anomaly markets (large absolute move, active turnover,
                                       funding anomaly, OI anomaly)
    fill (if < 30)                    (oldest valid last_llm_research_at)

The pool is hard-capped at ``MAX_POOL_SIZE`` symbols with enough compact facts
for the model to understand WHY each symbol appeared. No pool category grants
trading authority: appearing in the pool only means "worth research attention".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.market_data.opportunity.coverage import CoverageLedger

MAX_POOL_SIZE = 30
FACTOR_CAP = 10
ROTATION_CAP = 10
ACTIVE_CAP = 10

REASON_FACTOR_CANDIDATE = "factor candidate"
REASON_FAIR_ROTATION = "fair rotation"
REASON_ACTIVE_TURNOVER = "active turnover"
REASON_LARGE_ABS_MOVE = "large absolute move"
REASON_FUNDING_ANOMALY = "funding anomaly"
REASON_OI_ANOMALY = "OI anomaly"
REASON_LIQUIDITY_ANOMALY = "liquidity anomaly"
REASON_OLDEST_UNRESEARCHED = "oldest-unresearched fallback"


@dataclass(frozen=True, slots=True)
class PoolEntry:
    symbol: str
    reasons: tuple[str, ...]
    facts: dict = field(default_factory=dict)
    execution_supported: bool = False
    last_llm_research_at: str | None = None
    in_snapshot_candidate_set: bool = False

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "reasons": list(self.reasons),
            "facts": dict(self.facts),
            "execution_supported": self.execution_supported,
            "last_llm_research_at": self.last_llm_research_at,
        }


def _compact_facts(row: dict) -> dict:
    """Bounded factual summary per symbol (no histories, no secrets)."""
    return {
        "last_price": row.get("last"),
        "price_change_24h_pct": _round(row.get("price_change_24h_pct")),
        "estimated_quote_turnover_24h": _round(row.get("vol_usd_24h"), 0),
        "turnover_quality": "ESTIMATED" if row.get("vol_usd_24h") is not None else "MISSING",
        "funding_rate": row.get("funding_rate"),
        "funding_quality": row.get("funding_quality"),
        "funding_reason": row.get("funding_reason"),
        "open_interest": row.get("open_interest"),
        "ticker_quality": row.get("ticker_quality"),
        "eligible_for_observation": row.get("eligible"),
        "excluded_reasons": list(row.get("excluded_reasons") or ()),
    }


def _round(value, digits: int = 6):
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def build_research_pool(
    *,
    snapshot,
    ledger: CoverageLedger,
    max_size: int = MAX_POOL_SIZE,
    existing_positions: set[str] | None = None,
    now: datetime | None = None,
) -> list[PoolEntry]:
    """Build the bounded, deduplicated pool for one selection round."""
    if snapshot is None:
        return []
    now = now or datetime.now(UTC)
    existing_positions = existing_positions or set()
    rows = {row.get("symbol"): row for row in (snapshot.observable_rows or ())}
    entries: dict[str, PoolEntry] = {}

    def add(
        symbol: str,
        reason: str,
        *,
        facts: dict | None = None,
        candidate: bool = False,
    ) -> None:
        if not symbol or symbol in existing_positions:
            return
        current = entries.get(symbol)
        row_facts = (
            facts
            if facts is not None
            else _compact_facts(rows.get(symbol, {"symbol": symbol}))
        )
        if current is None:
            entries[symbol] = PoolEntry(
                symbol=symbol,
                reasons=(reason,),
                facts=row_facts,
                execution_supported=bool(rows.get(symbol, {}).get("execution_supported", True)),
                last_llm_research_at=ledger.as_dict(symbol).get("last_llm_research_at"),
                in_snapshot_candidate_set=candidate,
            )
        else:
            reasons = (
                current.reasons if reason in current.reasons else (*current.reasons, reason)
            )
            entries[symbol] = PoolEntry(
                symbol=symbol,
                reasons=reasons,
                facts=current.facts,
                execution_supported=current.execution_supported,
                last_llm_research_at=current.last_llm_research_at,
                in_snapshot_candidate_set=current.in_snapshot_candidate_set or candidate,
            )

    # 1) factor candidates (highest research attention, never trading authority)
    factor_symbols: list[str] = []
    for candidate in sorted(
        snapshot.factor_candidates, key=lambda c: (-c.strongest_strength, c.symbol)
    ):
        if candidate.is_expired(now=now):
            continue
        if len(factor_symbols) >= FACTOR_CAP:
            break
        factor_symbols.append(candidate.symbol)
        add(candidate.symbol, REASON_FACTOR_CANDIDATE, candidate=True)

    # 2) fair rotation — reserved capacity, never starved by hot candidates
    rotation_candidates = [
        symbol for symbol in (snapshot.rotation_symbols or ()) if symbol not in entries
    ]
    if not rotation_candidates:
        rotation_candidates = [
            symbol
            for symbol in ledger.oldest_llm_research_at_order(rows.keys())
            if symbol not in entries
        ]
    for symbol in rotation_candidates[:ROTATION_CAP]:
        add(symbol, REASON_FAIR_ROTATION)

    # 3) active / anomaly markets from factual broad facts. Symbols already in
    # the pool are NOT excluded here: the anomaly reason is merged so the model
    # still sees why the market is interesting.
    active_symbols = _active_symbols(rows, set())
    for symbol, reasons in active_symbols[:ACTIVE_CAP]:
        for reason in reasons:
            add(symbol, reason)

    # 4) fill with oldest valid last_llm_research_at
    if len(entries) < max_size:
        for symbol in ledger.oldest_llm_research_at_order(rows.keys()):
            if len(entries) >= max_size:
                break
            add(symbol, REASON_OLDEST_UNRESEARCHED)

    ordered = sorted(
        entries.values(),
        key=lambda e: (
            0 if REASON_FACTOR_CANDIDATE in e.reasons else 1,
            e.last_llm_research_at or "",
            e.symbol,
        ),
    )
    return ordered[:max_size]


def _active_symbols(rows: dict, excluded) -> list[tuple[str, tuple[str, ...]]]:
    """Factual active/anomaly nominations (attention only, never direction)."""
    scored: dict[str, list[str]] = {}

    movers = sorted(
        (
            row
            for row in rows.values()
            if row.get("price_change_24h_pct") is not None and row.get("vol_usd_24h")
        ),
        key=lambda row: -abs(row["price_change_24h_pct"]),
    )
    for row in movers[:ACTIVE_CAP]:
        scored.setdefault(row["symbol"], []).append(REASON_LARGE_ABS_MOVE)

    turnover_leaders = sorted(
        (row for row in rows.values() if row.get("vol_usd_24h")),
        key=lambda row: -(row["vol_usd_24h"] or 0.0),
    )
    for row in turnover_leaders[:ACTIVE_CAP]:
        scored.setdefault(row["symbol"], []).append(REASON_ACTIVE_TURNOVER)

    for row in rows.values():
        funding = row.get("funding_rate")
        if funding is not None and abs(funding) >= 0.0015:
            scored.setdefault(row["symbol"], []).append(REASON_FUNDING_ANOMALY)

    ordered = sorted(
        ((symbol, tuple(reasons)) for symbol, reasons in scored.items() if symbol not in excluded),
        key=lambda item: (-len(item[1]), item[0]),
    )
    return ordered
