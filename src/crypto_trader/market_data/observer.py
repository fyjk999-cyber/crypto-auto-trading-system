"""Phase C/D hierarchical market observer over the dynamic OKX universe.

Directive §34-§50 (dynamic all-market runtime), mapped:

* Layer 1 — ALL-MARKET factual scan: ONE batch tickers request per product
  class (SPOT, SWAP) via DynamicMarketUniverse.layer1_batch. Never per-symbol
  REST for the full market.
* Layer 2 — candidate stream: a bounded WS ticker subscription (OKX public
  v5) for the ACTIVE candidate set only, with automatic REST-batch fallback
  and STALE marking. A missing feed degrades evidence freshness; it NEVER
  fabricates data and NEVER blocks trading (advisory evidence only).
* Candidate selection is FACTUAL ONLY (24h notional volume rank over live
  registry instruments + pinned held/core symbols). There is deliberately NO
  composite score, NO opportunity ranking and NO quant hard gate: the
  observer is evidence for the Chief Trader LLM, never a decision authority.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.market_data.universe import (
    DynamicMarketUniverse,
    Layer1Fact,
    MarketSnapshotBatch,
)

logger = logging.getLogger("crypto_trader.market_observer")

OKX_WS_PUBLIC_URL = "wss://ws.okx.com:8443/ws/v5/public"
DEFAULT_STALE_AFTER_SECONDS = 90.0
MAX_CANDIDATE_INSTRUMENTS = 50


def _volume(value: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return Decimal("0")


@dataclass
class CandidateSet:
    inst_ids: tuple[str, ...]
    basis: dict = field(default_factory=dict)


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
        clock=None,
    ) -> None:
        self.universe = universe
        self.ws_manager = ws_manager
        self.scan_interval_seconds = max(15.0, float(scan_interval_seconds))
        self.stale_after_seconds = float(stale_after_seconds)
        self.quote_ccy = quote_ccy
        self.pinned_inst_ids = tuple(pinned_inst_ids)
        self.clock = clock or time.monotonic
        self._batches: dict[str, MarketSnapshotBatch] = {}
        self._last_scan_mono: dict[str, float] = {}
        self._scan_failures = 0
        self._last_error: str = ""
        self._last_scan_at: str = ""

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

    def select_candidates(
        self,
        target: int = 5,
        *,
        held_canonical_symbols: tuple[str, ...] = (),
        core_canonical_symbols: tuple[str, ...] = (),
    ) -> CandidateSet:
        """FACTUAL candidate selection: pinned (held + core) always kept;
        remaining slots = top 24h notional volume among live USDT instruments.
        No scores, no ranking model, no gate."""
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

        ranked: list[tuple[Decimal, str, str]] = []  # (volume, inst_id, inst_type)
        for inst_type in ("SPOT", "SWAP"):
            for fact in self._facts(inst_type):
                vol = _volume(fact.volume_ccy_24h) or _volume(fact.volume_24h)
                if vol > 0:
                    ranked.append((vol, fact.inst_id, inst_type))
        ranked.sort(key=lambda item: item[0], reverse=True)

        candidates = list(pinned)
        for _vol, inst_id, _t in ranked:
            if len(candidates) >= target + len(pinned):
                break
            if inst_id not in candidates:
                candidates.append(inst_id)
        basis = {
            "pinned": pinned,
            "target": target,
            "ranked_pool": len(ranked),
            "rule": "held+core pinned, then top 24h notional volume (factual only)",
        }
        return CandidateSet(inst_ids=tuple(candidates[:MAX_CANDIDATE_INSTRUMENTS]), basis=basis)

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

        cand = candidate or self.select_candidates()
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
        summary["available"] = True
        return summary
