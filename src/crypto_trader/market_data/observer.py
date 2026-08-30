"""Phase C/D hierarchical market observer over the dynamic OKX universe.

Directive §34-§50 (dynamic all-market runtime), mapped:

* Layer 1 — ALL-MARKET factual scan: ONE batch tickers request per product
  class (SPOT, SWAP) via DynamicMarketUniverse.layer1_batch. Never per-symbol
  REST for the full market.
* Layer 2 — candidate stream: a bounded WS ticker subscription (OKX public
  v5) for the ACTIVE candidate set only, with automatic REST-batch fallback
  and STALE marking. A missing feed degrades evidence freshness; it NEVER
  fabricates data and NEVER blocks trading (advisory evidence only).
* Non-core attention selection (P1 CS-20260830-034530-P3-AI-ATTENTION) is
  owned by the MARKET OBSERVER AI over a bounded, compressed all-market
  digest. Factual volume/liquidity are evidence inside that context and
  carry NO eligibility authority: there is NO 24h-volume Top-K, NO
  composite score, NO quant gate, and NO rank fallback when the AI is
  unavailable. Deterministic exclusions are limited to genuine
  availability/safety facts (no quote, stale batch) and pinned held/core
  protection; execution capability is granted nowhere in this module.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.market_data.attention import (
    AttentionDecision,
    build_market_digest,
    new_attention_uid,
)
from crypto_trader.market_data.universe import (
    DynamicMarketUniverse,
    Layer1Fact,
    MarketSnapshotBatch,
)

logger = logging.getLogger("crypto_trader.market_observer")

OKX_WS_PUBLIC_URL = "wss://ws.okx.com:8443/ws/v5/public"
DEFAULT_STALE_AFTER_SECONDS = 90.0
MAX_CANDIDATE_INSTRUMENTS = 50
DEFAULT_ATTENTION_REFRESH_SECONDS = 300.0

ATTENTION_RULE = (
    "held+core pinned, then Market Observer AI attention over a bounded "
    "compressed all-market roster (no volume/Top-K authority)"
)


def _volume(value: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return Decimal("0")


@dataclass
class CandidateSet:
    inst_ids: tuple[str, ...]
    basis: dict = field(default_factory=dict)
    attention: AttentionDecision | None = None


class OKXTickerWsManager:
    """Bounded WS tickers subscription with REST fallback semantics.

    This manager never raises into trading: connection failures flip the
    manager to FALLBACK (REST) mode and a background task keeps retrying.
    Consumers read `snapshot(inst_ids)` and `healthy`.
    """

    def __init__(self, url: str = OKX_WS_PUBLIC_URL) -> None:
        self.url = url
        self._inst_ids: tuple[str, ...] = ()
        self._latest: dict[str, dict] = {}
        self._last_msg_mono: float = 0.0
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._connect_failures = 0
        self._resubscribe_requested = False

    # ------------------------------------------------------------- control
    def set_instruments(self, inst_ids: tuple[str, ...]) -> None:
        bounded = tuple(dict.fromkeys(inst_ids))[:MAX_CANDIDATE_INSTRUMENTS]
        if bounded != self._inst_ids:
            self._inst_ids = bounded
            self._resubscribe_requested = True

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._run(), name="okx-ticker-ws")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    # -------------------------------------------------------------- status
    @property
    def healthy(self) -> bool:
        return (
            bool(self._latest)
            and (time.monotonic() - self._last_msg_mono) < DEFAULT_STALE_AFTER_SECONDS
        )

    @property
    def mode(self) -> str:
        return "WS" if self.healthy else "FALLBACK"

    def snapshot(self, inst_ids: tuple[str, ...]) -> dict[str, dict]:
        return {i: self._latest[i] for i in inst_ids if i in self._latest}

    # ------------------------------------------------------------ internals
    async def _run(self) -> None:  # pragma: no cover - network loop
        import websockets  # optional dependency, lazy import

        while not self._stop.is_set():
            if not self._inst_ids:
                await asyncio.sleep(1.0)
                continue
            try:
                async with websockets.connect(self.url, ping_interval=20) as ws:
                    args = [{"channel": "tickers", "instId": i} for i in self._inst_ids]
                    await ws.send(json.dumps({"op": "subscribe", "args": args}))
                    self._connect_failures = 0
                    self._resubscribe_requested = False
                    async for raw in ws:
                        self._last_msg_mono = time.monotonic()
                        self._ingest(raw)
                        if self._stop.is_set() or self._resubscribe_requested:
                            # Reconnect re-subscribes with the new set.
                            break
            except asyncio.CancelledError:
                raise
            except Exception:
                self._connect_failures += 1
                await asyncio.sleep(min(30.0, 2.0 * self._connect_failures))

    def _ingest(self, raw) -> None:
        try:
            msg = json.loads(raw)
        except (TypeError, ValueError):
            return
        for row in msg.get("data") or []:
            inst_id = str(row.get("instId") or "")
            if inst_id:
                self._latest[inst_id] = row


class HierarchicalMarketObserver:
    """All-market Layer-1 scan + bounded candidate stream, advisory only."""

    def __init__(
        self,
        universe: DynamicMarketUniverse,
        *,
        ws_manager: OKXTickerWsManager | None = None,
        scan_interval_seconds: float = 60.0,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
        quote_ccy: str = "USDT",
        pinned_inst_ids: tuple[str, ...] = (),
        attention_selector=None,
        attention_refresh_seconds: float = DEFAULT_ATTENTION_REFRESH_SECONDS,
        attention_lineage_sink=None,
        clock=None,
    ) -> None:
        self.universe = universe
        self.ws_manager = ws_manager
        self.scan_interval_seconds = max(15.0, float(scan_interval_seconds))
        self.stale_after_seconds = float(stale_after_seconds)
        self.quote_ccy = quote_ccy
        self.pinned_inst_ids = tuple(pinned_inst_ids)
        # Market Observer AI (P3 correction): owns non-core attention. When
        # absent, dynamic slots stay EMPTY (AI_NOT_CONFIGURED) -- never a
        # volume-rank fallback.
        self.attention_selector = attention_selector
        self.attention_refresh_seconds = max(30.0, float(attention_refresh_seconds))
        self.attention_lineage_sink = attention_lineage_sink
        self.clock = clock or time.monotonic
        self._batches: dict[str, MarketSnapshotBatch] = {}
        self._last_scan_mono: dict[str, float] = {}
        self._scan_failures = 0
        self._last_error: str = ""
        self._last_scan_at: str = ""
        # Attention state (AI-owned selection + lineage).
        self._last_attention: AttentionDecision | None = None
        self._last_attention_refresh_mono: float = 0.0
        self._attention_refreshes = 0
        self._attention_failures = 0
        self._attention_sink_failures = 0

    # ------------------------------------------------------------- Layer 1
    async def _scan_layer1(self, inst_type: str) -> None:
        try:
            batch = await self.universe.layer1_batch(inst_type)
            self._batches[inst_type] = batch
            self._last_scan_mono[inst_type] = self.clock()
            self._scan_failures = 0
            self._last_error = ""
            self._last_scan_at = batch.captured_at
        except Exception as exc:
            # Keep the previous batch but mark it stale below; never fabricate.
            self._scan_failures += 1
            self._last_error = f"{type(exc).__name__}: {exc}"[:200]
            logger.warning("LAYER1_SCAN_FAILED inst_type=%s error=%s", inst_type, self._last_error)

    async def poll(self, force: bool = False) -> None:
        """Throttled all-market refresh (SPOT + SWAP). Safe to call per tick."""
        now = self.clock()
        for inst_type in ("SPOT", "SWAP"):
            last = self._last_scan_mono.get(inst_type, 0.0)
            if force or now - last >= self.scan_interval_seconds:
                await self._scan_layer1(inst_type)

    # ---------------------------------------------------------- candidates
    def _facts(self, inst_type: str, *, allow_stale: bool = True) -> list[Layer1Fact]:
        batch = self._batches.get(inst_type)
        if batch is None:
            return []
        cutoff = self.clock() - self.stale_after_seconds * 10
        _ = cutoff  # freshness handled per fact below
        return list(batch.facts)

    def _fact_freshness(self, inst_type: str) -> str:
        last = self._last_scan_mono.get(inst_type, 0.0)
        if not last:
            return "NOT_AVAILABLE"
        return "LIVE" if (self.clock() - last) <= self.stale_after_seconds else "STALE"

    # ----------------------------------------------------------- attention
    async def select_candidates(
        self,
        target: int = 5,
        *,
        held_canonical_symbols: tuple[str, ...] = (),
        core_canonical_symbols: tuple[str, ...] = (),
    ) -> CandidateSet:
        """Pinned (held + core) always kept; remaining slots are filled by
        MARKET OBSERVER AI attention over the compressed all-market digest.

        P1 CS-20260830-034530-P3-AI-ATTENTION correction: the former 24h
        notional volume Top-K is REMOVED. Factual volume is evidence inside
        the digest, never an eligibility decision. When the AI is
        unavailable or not configured the dynamic slots stay empty (honest
        absence, recorded in lineage) -- no rank fallback exists.
        """
        target = max(1, min(int(target), 20))
        mapper = SymbolMapper()
        pinned: list[str] = []

        def to_inst(symbol: str) -> str | None:
            canonical = mapper.to_canonical(symbol)
            base = canonical.removesuffix("USDT") or canonical
            spot = f"{base}-USDT"
            swap = f"{base}-USDT-SWAP"
            known: set[str] = set()
            for inst_type in ("SPOT", "SWAP"):
                batch = self._batches.get(inst_type)
                if batch is not None:
                    known |= {f.inst_id for f in batch.facts}
            for inst in (swap, spot):
                if inst in known:
                    return inst
            return None

        for symbol in (*held_canonical_symbols, *core_canonical_symbols):
            inst = to_inst(symbol)
            if inst and inst not in pinned:
                pinned.append(inst)
        for inst in self.pinned_inst_ids:
            if inst not in pinned:
                pinned.append(inst)

        slots = max(0, target - len(pinned))
        attention = await self._refresh_attention(
            slots=slots, pinned=tuple(pinned)
        )
        dynamic = [i for i in attention.selected_inst_ids if i not in pinned]

        candidates = list(pinned)
        for inst_id in dynamic:
            if len(candidates) >= target:
                break
            candidates.append(inst_id)
        basis = {
            "pinned": pinned,
            "target": target,
            "universe_size": attention.universe_size,
            "roster_size": attention.roster_size,
            "attention_uid": attention.attention_uid,
            "attention_mode": attention.mode,
            "rule": ATTENTION_RULE,
        }
        return CandidateSet(
            inst_ids=tuple(candidates[:MAX_CANDIDATE_INSTRUMENTS]),
            basis=basis,
            attention=attention,
        )

    def select_pinned_only(self) -> tuple[str, ...]:
        """Sync pinned-only projection (held/core/observer pins).

        Used by the sync snapshot path only; it grants no dynamic attention
        and never applies a rank rule.
        """
        known: set[str] = set()
        for inst_type in ("SPOT", "SWAP"):
            batch = self._batches.get(inst_type)
            if batch is not None:
                known |= {f.inst_id for f in batch.facts}
        out: list[str] = []
        for inst in self.pinned_inst_ids:
            if inst in known and inst not in out:
                out.append(inst)
        return tuple(out[:MAX_CANDIDATE_INSTRUMENTS])

    async def _refresh_attention(
        self, *, slots: int, pinned: tuple[str, ...]
    ) -> AttentionDecision:
        """AI attention with bounded refresh throttling; never raises.

        Between refreshes the previous AI selection is carried forward
        (explicitly labelled carried_forward) -- a missing/failing LLM call
        degrades to honest absence, never to volume rank.
        """
        now = self.clock()
        due = (
            now - self._last_attention_refresh_mono
        ) >= self.attention_refresh_seconds
        if not due and self._last_attention is not None:
            return self._last_attention

        if self.attention_selector is None:
            decision = AttentionDecision(
                attention_uid=new_attention_uid(),
                created_at=self._utc_now(),
                mode="AI_NOT_CONFIGURED",
                cache_state="NOT_APPLICABLE",
                universe_size=self._universe_size(),
            )
            self._last_attention = decision
            self._last_attention_refresh_mono = now
            return decision

        freshness = {t: self._fact_freshness(t) for t in ("SPOT", "SWAP")}
        try:
            digest = build_market_digest(
                {
                    t: b
                    for t, b in self._batches.items()
                    if isinstance(b, MarketSnapshotBatch)
                },
                freshness_by_type=freshness,
                pinned_inst_ids=pinned,
                rotation_offset=self._attention_refreshes,
            )
        except Exception as exc:
            self._attention_failures += 1
            decision = AttentionDecision(
                attention_uid=new_attention_uid(),
                created_at=self._utc_now(),
                mode="AI_UNAVAILABLE",
                cache_state="REFRESH",
                error=f"DIGEST_FAILED:{type(exc).__name__}"[:200],
                universe_size=self._universe_size(),
                carried_forward=self._last_attention is not None,
            )
            self._last_attention = decision
            self._last_attention_refresh_mono = now
            return decision

        started = time.monotonic()
        try:
            selected, meta = await self.attention_selector.select(
                digest, slots=slots, pinned_inst_ids=pinned
            )
        except Exception as exc:  # selector contract: never raises, but stay safe
            selected, meta = (), {
                "mode": "AI_UNAVAILABLE",
                "rationale": "",
                "llm_invocation_id": "",
                "error": f"{type(exc).__name__}: {exc}"[:200],
                "roster_size": len(digest.get("roster") or []),
            }
        latency_ms = int((time.monotonic() - started) * 1000)
        mode = str(meta.get("mode") or "AI_UNAVAILABLE")
        carried = bool(self._last_attention is not None) and mode != "AI_SELECTED"
        decision = AttentionDecision(
            attention_uid=new_attention_uid(),
            created_at=self._utc_now(),
            mode=mode,
            selected_inst_ids=tuple(selected),
            rationale=str(meta.get("rationale") or "")[:255],
            llm_invocation_id=str(meta.get("llm_invocation_id") or "")[:64],
            latency_ms=latency_ms,
            cache_state="REFRESH",
            error=str(meta.get("error") or "")[:255],
            roster_size=int(meta.get("roster_size") or 0),
            universe_size=int((digest.get("universe") or {}).get("total") or 0),
            quoted_size=int((digest.get("universe") or {}).get("quoted") or 0),
            excluded_unavailable=int(
                (digest.get("universe") or {}).get("unavailable_no_quote") or 0
            ),
            buckets=dict(digest.get("buckets") or {}),
            input_digest=str(digest.get("input_digest") or "")[:64],
            layer1_batch_ids={
                t: b.batch_id
                for t, b in self._batches.items()
                if isinstance(b, MarketSnapshotBatch)
            },
            carried_forward=carried,
            version=getattr(self.attention_selector, "version", ""),
        )
        self._last_attention = decision
        self._last_attention_refresh_mono = now
        if mode == "AI_SELECTED":
            self._attention_refreshes += 1
        else:
            self._attention_failures += 1
        await self._persist_attention_lineage(decision, pinned)
        return decision

    async def _persist_attention_lineage(
        self, decision: AttentionDecision, pinned: tuple[str, ...]
    ) -> None:
        """Fail-safe durable attention lineage (DB validation contract)."""
        if self.attention_lineage_sink is None:
            return
        try:
            row = decision.to_row()
            row["pinned_inst_ids"] = list(pinned)
            result = self.attention_lineage_sink(row)
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            self._attention_sink_failures += 1
            logger.warning(
                "ATTENTION_LINEAGE_PERSIST_FAILED failures=%d error=%s",
                self._attention_sink_failures,
                type(exc).__name__,
            )

    def _universe_size(self) -> int:
        return sum(
            len(b.facts)
            for b in self._batches.values()
            if isinstance(b, MarketSnapshotBatch)
        )

    @staticmethod
    def _utc_now() -> str:
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat()

    def update_ws_candidates(self, candidate: CandidateSet) -> None:
        """Keep the bounded WS subscription aligned with the candidate set."""
        if self.ws_manager is not None:
            self.ws_manager.set_instruments(candidate.inst_ids)

    @staticmethod
    def canonical_symbols_for(candidate: CandidateSet) -> tuple[str, ...]:
        """inst_id -> canonical trading symbol (BTC-USDT-SWAP -> BTCUSDT)."""
        out: list[str] = []
        for inst_id in candidate.inst_ids:
            base = inst_id.split("-")[0]
            if base and f"{base}USDT" not in out:
                out.append(f"{base}USDT")
        return tuple(out)

    # -------------------------------------------------------------- observe
    def observe(self, candidate: CandidateSet | None = None) -> dict:
        """Compact hierarchical summary for the Chief Trader context.

        Layer 1 = all-market breadth (factual counts). Layer 2 = candidate
        facts (WS when healthy, REST batch otherwise) with explicit
        freshness. Advisory only: absent on failure, never blocks.
        """
        summary: dict = {"source": self.ws_manager.mode if self.ws_manager else "REST"}
        spot_batch = self._batches.get("SPOT")
        swap_batch = self._batches.get("SWAP")
        if spot_batch is None and swap_batch is None:
            return {
                "available": False,
                "reason": self._last_error or "no layer1 batch yet",
                "scan_failures": self._scan_failures,
            }
        breadth: dict[str, dict] = {}
        for inst_type, batch in (("SPOT", spot_batch), ("SWAP", swap_batch)):
            if batch is None:
                continue
            two_sided = sum(
                1 for f in batch.facts if f.bid != "NOT_AVAILABLE" and f.ask != "NOT_AVAILABLE"
            )
            total_vol = sum((_volume(f.volume_ccy_24h) for f in batch.facts), Decimal("0"))
            breadth[inst_type] = {
                "instruments": len(batch.facts),
                "two_sided_quotes": two_sided,
                "volume_ccy_24h_sum": str(total_vol),
                "captured_at": batch.captured_at,
                "freshness": self._fact_freshness(inst_type),
            }
        summary["market_breadth"] = breadth
        summary["last_scan_at"] = self._last_scan_at
        if self._last_error:
            summary["last_error"] = self._last_error

        if candidate is not None:
            cand = candidate
        else:
            # Sync snapshot path: reuse the LAST AI attention outcome instead
            # of re-selecting (selection is async + AI-owned). Empty when no
            # attention has been produced yet; never a rank fallback.
            pinned_only = self.select_pinned_only()
            cand = CandidateSet(
                inst_ids=pinned_only,
                basis={
                    "pinned": list(pinned_only),
                    "rule": ATTENTION_RULE,
                    "attention_mode": (
                        self._last_attention.mode if self._last_attention else "NONE_YET"
                    ),
                },
                attention=self._last_attention,
            )
        facts: dict[str, dict] = {}
        ws_snap = (
            self.ws_manager.snapshot(cand.inst_ids)
            if self.ws_manager is not None
            else {}
        )
        all_batch_facts: dict[str, Layer1Fact] = {}
        for inst_type in ("SPOT", "SWAP"):
            for f in self._facts(inst_type):
                all_batch_facts[f.inst_id] = f
        for inst_id in cand.inst_ids:
            if inst_id in ws_snap:
                row = ws_snap[inst_id]
                facts[inst_id] = {
                    "last": str(row.get("last") or "NOT_AVAILABLE"),
                    "bid": str(row.get("bidPx") or "NOT_AVAILABLE"),
                    "ask": str(row.get("askPx") or "NOT_AVAILABLE"),
                    "vol24h": str(row.get("vol24h") or "NOT_AVAILABLE"),
                    "volCcy24h": str(row.get("volCcy24h") or "NOT_AVAILABLE"),
                    "ts": str(row.get("ts") or ""),
                    "freshness": "LIVE",
                    "source": "WS",
                }
            elif inst_id in all_batch_facts:
                f = all_batch_facts[inst_id]
                facts[inst_id] = {
                    **f.to_dict(),
                    "freshness": self._fact_freshness(f.inst_type),
                    "source": "REST_BATCH",
                }
        summary["candidates"] = {"basis": cand.basis, "facts": facts}
        attention = getattr(cand, "attention", None) or self._last_attention
        if attention is not None:
            summary["attention"] = attention.to_bounded_dict()
        summary["available"] = True
        return summary
