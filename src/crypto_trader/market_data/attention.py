"""Market Observer AI attention (P1 CS-20260830-034530-P3-AI-ATTENTION).

Directive correction: non-core attention over the dynamic OKX all-market
universe is owned by a MARKET OBSERVER AI, not by a 24h notional volume
Top-K. Quantitative facts (volume, spread, 24h range position) remain
EVIDENCE inside a bounded, compressed all-market context; they can never
deterministically close the universe to AI attention.

Design (AI-FIRST / QUANT-AS-EVIDENCE):

* ``build_market_digest`` compresses EVERY live Layer-1 fact into a fixed
  set of factual 24h-range buckets. Every instrument with a two-sided quote
  falls into exactly one bucket and every bucket contributes identities to
  the bounded roster (deterministic uniform stride over inst_id -- never a
  volume rank). No instrument is excluded for rank; exclusions are limited
  to genuine availability/safety facts (no quote, stale batch).
* ``LLMMarketAttentionSelector`` hands that digest to the LLM and owns the
  non-core attention selection. Its output is the ONLY source of dynamic
  rotation slots. There is deliberately NO rank fallback: when the AI is
  unavailable the dynamic slots stay EMPTY (honest absence, recorded in
  lineage) -- volume Top-K must never silently return.
* Execution capability is NOT granted here. Attention only widens which
  reference symbols reach the Chief Trader; Decision -> Risk -> Execution
  authority chains are unchanged downstream.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from crypto_trader.market_data.universe import MarketSnapshotBatch

# Fixed factual buckets by position of last price inside the 24h high/low
# range (range_pos = (last - low) / (high - low)). Buckets cover the whole
# [0, 1] domain plus missing/unavailable states.
ATTENTION_BUCKETS: tuple[str, ...] = (
    "NEAR_HIGH",  # range_pos >= 0.90
    "UPPER",      # >= 0.75
    "MID_UPPER",  # >= 0.50
    "MID_LOWER",  # >= 0.25
    "LOWER",      # >= 0.10
    "NEAR_LOW",   # < 0.10
    "NO_RANGE",   # high == low or unavailable
    "NO_QUOTE",   # bid/ask missing (genuine availability exclusion)
)

DEFAULT_ROSTER_PER_BUCKET = 6
DEFAULT_MAX_ROSTER = 60
MAX_PINNED_IN_DIGEST = 40


def _num(value: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _range_pos(fact) -> str:
    """Position of last inside the 24h range, as bounded decimal string."""
    try:
        last = _num(fact.last)
        high = _num(fact.high_24h)
        low = _num(fact.low_24h)
        if last <= 0 or high <= 0 or low <= 0 or high <= low:
            return "NOT_AVAILABLE"
        return str(((last - low) / (high - low)).quantize(Decimal("0.0001")))
    except Exception:
        return "NOT_AVAILABLE"


def _spread_bps(fact) -> str:
    try:
        bid, ask = _num(fact.bid), _num(fact.ask)
        mid = (bid + ask) / 2
        if bid <= 0 or ask <= 0 or mid <= 0:
            return "NOT_AVAILABLE"
        return str(((ask - bid) / mid * Decimal("10000")).quantize(Decimal("0.01")))
    except Exception:
        return "NOT_AVAILABLE"


def _bucket_for(fact) -> str:
    if fact.bid == "NOT_AVAILABLE" or fact.ask == "NOT_AVAILABLE":
        return "NO_QUOTE"
    pos = _range_pos(fact)
    if pos == "NOT_AVAILABLE":
        return "NO_RANGE"
    p = float(pos)
    if p >= 0.90:
        return "NEAR_HIGH"
    if p >= 0.75:
        return "UPPER"
    if p >= 0.50:
        return "MID_UPPER"
    if p >= 0.25:
        return "MID_LOWER"
    if p >= 0.10:
        return "LOWER"
    return "NEAR_LOW"


@dataclass
class AttentionDecision:
    """One Market Observer AI attention outcome (lineage record)."""

    attention_uid: str = ""
    created_at: str = ""
    mode: str = "AI_NOT_CONFIGURED"
    selected_inst_ids: tuple[str, ...] = ()
    rationale: str = ""
    llm_invocation_id: str = ""
    latency_ms: int = 0
    cache_state: str = "NOT_APPLICABLE"
    error: str = ""
    roster_size: int = 0
    universe_size: int = 0
    quoted_size: int = 0
    excluded_unavailable: int = 0
    buckets: dict = field(default_factory=dict)
    input_digest: str = ""
    layer1_batch_ids: dict = field(default_factory=dict)
    carried_forward: bool = False
    version: str = ""

    def to_bounded_dict(self) -> dict:
        """Bounded projection for decision evidence / audit (no payloads)."""
        return {
            "attention_uid": self.attention_uid,
            "created_at": self.created_at,
            "mode": self.mode,
            "selected_inst_ids": list(self.selected_inst_ids)[:24],
            "rationale": self.rationale[:255],
            "llm_invocation_id": self.llm_invocation_id,
            "latency_ms": int(self.latency_ms),
            "cache_state": self.cache_state,
            "error": self.error[:200],
            "roster_size": self.roster_size,
            "universe_size": self.universe_size,
            "quoted_size": self.quoted_size,
            "excluded_unavailable": self.excluded_unavailable,
            "buckets": dict(self.buckets),
            "input_digest": self.input_digest,
            "carried_forward": self.carried_forward,
            "selector_version": self.version,
        }

    def to_row(self) -> dict:
        """Persistence row for market_attention_decisions (ORM-shaped).

        JSON columns receive plain Python objects (the ORM serializes);
        ``created_at`` is left to the column default. Strings are bounded.
        """
        return {
            "attention_uid": self.attention_uid[:64],
            "mode": self.mode[:16],
            "selected_inst_ids": list(self.selected_inst_ids),
            "pinned_inst_ids": [],
            "roster_size": int(self.roster_size),
            "universe_size": int(self.universe_size),
            "buckets_json": dict(self.buckets),
            "rationale": self.rationale[:255],
            "llm_invocation_id": self.llm_invocation_id[:64] or None,
            "input_digest": self.input_digest[:64],
            "latency_ms": int(self.latency_ms),
            "cache_state": self.cache_state[:16],
            "error": self.error[:255],
            "layer1_batch_ids": dict(self.layer1_batch_ids),
            "selector_version": self.version[:32],
        }


def _in_observable_universe(inst_id: str) -> bool:
    """Registry observable-universe contract (DynamicMarketUniverse):
    live instruments quoted in USDT (spot ``*-USDT`` / swap ``*-USDT-SWAP``).
    Other quote currencies are OUT OF UNIVERSE by definition -- a registry
    fact, never a rank/quant eligibility veto."""
    return inst_id.endswith("-USDT") or inst_id.endswith("-USDT-SWAP")


def build_market_digest(
    batches: dict[str, MarketSnapshotBatch],
    *,
    freshness_by_type: dict[str, str],
    pinned_inst_ids: tuple[str, ...] = (),
    roster_per_bucket: int = DEFAULT_ROSTER_PER_BUCKET,
    max_roster: int = DEFAULT_MAX_ROSTER,
    rotation_offset: int = 0,
) -> dict:
    """Bounded, compressed ALL-MARKET representation for attention AI.

    Compression contract (hierarchical, non-quantitative):

    * every fact lands in exactly ONE fixed bucket by factual 24h-range
      position; bucket COUNTS cover the entire live universe;
    * bucket identities enter the roster via a deterministic uniform stride
      over lexicographic inst_id -- uniform coverage, never a volume rank;
    * ``rotation_offset`` advances the stride window each refresh so EVERY
      instrument reaches AI consideration within a bounded number of
      refreshes (no static subset holds attention authority);
    * only genuine availability facts exclude an instrument (NO_QUOTE) or
      mark its batch stale. Nothing is excluded for rank/threshold.
    """
    per_bucket_cap = max(2, int(max_roster) // max(1, len(ATTENTION_BUCKETS)))
    buckets: dict[str, dict] = {
        name: {"count": 0, "stale": 0, "inst_ids": []} for name in ATTENTION_BUCKETS
    }
    universe_by_type: dict[str, int] = {}
    quoted = 0
    unavailable = 0
    out_of_universe = 0
    for inst_type in ("SPOT", "SWAP"):
        batch = batches.get(inst_type)
        if batch is None:
            universe_by_type[inst_type] = 0
            continue
        universe_by_type[inst_type] = len(batch.facts)
        fresh = freshness_by_type.get(inst_type, "NOT_AVAILABLE") == "LIVE"
        for fact in batch.facts:
            if not _in_observable_universe(fact.inst_id):
                out_of_universe += 1
                continue
            bucket = _bucket_for(fact)
            if bucket == "NO_QUOTE":
                unavailable += 1
            else:
                quoted += 1
            slot = buckets[bucket]
            slot["count"] += 1
            if not fresh:
                slot["stale"] += 1
            if fresh and bucket != "NO_QUOTE":
                slot["inst_ids"].append(fact.inst_id)

    roster: list[dict] = []
    for name in ATTENTION_BUCKETS:
        slot = buckets.pop(name)  # type: ignore[arg-type]
        ids = sorted(set(slot.pop("inst_ids")))
        if ids:
            # Deterministic BLOCK rotation: refresh g shows the g-th block of
            # ``per_bucket_cap`` identities (cyclic). No rank, no randomness;
            # after ceil(len/cap) refreshes EVERY instrument in the bucket has
            # had an AI-consideration turn.
            cap = min(per_bucket_cap, len(ids))
            start = (int(rotation_offset) * cap) % len(ids)
            sampled = [ids[(start + j) % len(ids)] for j in range(cap)]
        else:
            sampled = []
        buckets[name] = {"count": slot["count"], "stale": slot["stale"], "sampled": len(sampled)}
        by_id: dict[str, object] = {}
        for inst_type in ("SPOT", "SWAP"):
            batch = batches.get(inst_type)
            if batch is None:
                continue
            for fact in batch.facts:
                by_id.setdefault(fact.inst_id, fact)
        for inst_id in sampled:
            fact = by_id.get(inst_id)
            if fact is None:
                continue
            roster.append(
                {
                    "inst_id": fact.inst_id,
                    "inst_type": fact.inst_type,
                    "last": str(fact.last)[:24],
                    "range_pos_24h": _range_pos(fact),
                    "spread_bps": _spread_bps(fact),
                    "vol_ccy_24h": str(fact.volume_ccy_24h)[:24],
                    "freshness": freshness_by_type.get(fact.inst_type, "NOT_AVAILABLE"),
                }
            )

    total = sum(universe_by_type.values())
    digest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "universe": {
            **universe_by_type,
            "total": total,
            "quoted": quoted,
            "unavailable_no_quote": unavailable,
            "out_of_universe_quote": out_of_universe,
        },
        "freshness": dict(freshness_by_type),
        "buckets": buckets,
        "roster": roster,
        "pinned_inst_ids": list(pinned_inst_ids)[:MAX_PINNED_IN_DIGEST],
        "note": (
            "volume/liquidity are factual evidence inside this context; they "
            "carry NO eligibility authority. Attention selection is owned by "
            "the Market Observer AI within the caller's slot bound."
        ),
    }
    digest["input_digest"] = hashlib.sha256(
        json.dumps(
            {
                "buckets": buckets,
                "universe": digest["universe"],
                "roster_ids": [r["inst_id"] for r in roster],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:32]
    return digest


class LLMMarketAttentionSelector:
    """Market Observer AI: owns non-core attention selection (advisory-free).

    The selector NEVER falls back to volume rank. On any failure it returns
    an AI_UNAVAILABLE outcome and the caller keeps the dynamic slots empty
    (or carries the previous AI selection forward, explicitly labelled).
    """

    version = "1.0.0"

    def __init__(
        self,
        complete_json,
        *,
        timeout_seconds: float = 20.0,
        max_selected: int = 20,
    ) -> None:
        # ``complete_json`` is the canonical gateway adapter call
        # (async, keyword: prompt). Injected so tests can stub it.
        self._complete_json = complete_json
        self.timeout_seconds = float(timeout_seconds)
        self.max_selected = max(1, min(int(max_selected), 20))

    async def select(
        self,
        digest: dict,
        *,
        slots: int,
        pinned_inst_ids: tuple[str, ...] = (),
    ) -> tuple[tuple[str, ...], dict]:
        """Return (selected_inst_ids, meta) where meta carries lineage facts."""
        if slots <= 0:
            return (), {
                "mode": "AI_SELECTED",
                "rationale": "no dynamic slots available (pinned fills the bound)",
                "llm_invocation_id": "",
                "error": "",
                "roster_size": len(digest.get("roster") or []),
            }
        roster_ids = [row["inst_id"] for row in digest.get("roster") or []]
        prompt = self._prompt(digest, slots=slots, pinned=list(pinned_inst_ids))
        error = ""
        parsed: dict = {}
        invocation_id = ""
        try:
            response = await self._complete_json(prompt=prompt)
            parsed = getattr(response, "parsed_json", None) or {}
            invocation_id = str(getattr(response, "invocation_id", "") or "")
            if not getattr(response, "ok", False):
                error = str(getattr(response, "error", "") or "LLM_ERROR")[:200]
        except Exception as exc:  # never propagates into the decision path
            error = f"{type(exc).__name__}: {exc}"[:200]
        if error or not isinstance(parsed, dict) or not parsed:
            return (), {
                "mode": "AI_UNAVAILABLE",
                "rationale": "",
                "llm_invocation_id": invocation_id,
                "error": error or "EMPTY_OR_MALFORMED_ATTENTION_RESPONSE",
                "roster_size": len(roster_ids),
            }
        allowed = set(roster_ids) | set(pinned_inst_ids)
        selected: list[str] = []
        rejected = 0
        raw = parsed.get("selected") or parsed.get("attention_selected") or []
        if not isinstance(raw, list):
            raw = []
        for item in raw:
            inst = str(item or "").strip()
            if not inst:
                continue
            if inst not in allowed:
                rejected += 1
                continue
            if inst not in selected:
                selected.append(inst)
            if len(selected) >= min(slots, self.max_selected):
                break
        meta = {
            "mode": "AI_SELECTED",
            "rationale": str(parsed.get("rationale") or "")[:255],
            "llm_invocation_id": invocation_id,
            "error": "",
            "roster_size": len(roster_ids),
            "rejected_selections": rejected,
        }
        return tuple(selected), meta

    def _prompt(self, digest: dict, *, slots: int, pinned: list[str]) -> str:
        buckets = digest.get("buckets") or {}
        bucket_lines = "\n".join(
            f"- {name}: total={stats.get('count', 0)} stale={stats.get('stale', 0)}"
            f" sampled={stats.get('sampled', 0)}"
            for name, stats in buckets.items()
        )
        roster_lines = "\n".join(
            f"- {row['inst_id']} type={row['inst_type']} last={row['last']} "
            f"range_pos_24h={row['range_pos_24h']} spread_bps={row['spread_bps']} "
            f"vol_ccy_24h={row['vol_ccy_24h']} freshness={row['freshness']}"
            for row in digest.get("roster") or []
        )
        universe = digest.get("universe") or {}
        return (
            "You are the Market Observer AI of a PAPER-only, AI-first trading "
            "runtime. You own NON-CORE attention: choose which observable "
            "instruments the Chief Trader should examine next. Volume, spread "
            "and 24h-range data are FACTUAL EVIDENCE ONLY - no threshold, "
            "rank or liquidity rule may decide eligibility.\n\n"
            f"Universe: SPOT={universe.get('SPOT', 0)} SWAP={universe.get('SWAP', 0)} "
            f"total={universe.get('total', 0)} quoted={universe.get('quoted', 0)} "
            f"unavailable={universe.get('unavailable_no_quote', 0)} "
            f"out_of_universe={universe.get('out_of_universe_quote', 0)}\n"
            f"Freshness: {json.dumps(digest.get('freshness') or {})}\n"
            "Fixed factual buckets over the WHOLE universe "
            "(count=total instruments, sampled=identities in roster):\n"
            f"{bucket_lines}\n\n"
            f"Roster (uniform deterministic coverage of every bucket, bounded):\n"
            f"{roster_lines}\n\n"
            f"Pinned instruments (held/core, always attended): "
            f"{json.dumps(pinned[:MAX_PINNED_IN_DIGEST])}\n\n"
            f"Task: select up to {slots} inst_ids from the roster for AI "
            "attention. Consider market-structure evidence (range position, "
            "spread, activity), diversity across buckets, and staleness "
            "risk. You MAY select fewer. Never invent inst_ids.\n"
            'Reply with STRICT JSON: {"selected": ["<inst_id>", ...], '
            '"rationale": "<=200 chars factual rationale"}'
        )


def new_attention_uid() -> str:
    return f"att-{uuid.uuid4().hex[:26]}"
