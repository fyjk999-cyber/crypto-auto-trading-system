"""Per-symbol factual evidence router (MASTER DIRECTIVE §26/§27/§28).

The canonical runtime previously ran ONE MultiStrategyAlpha bound to
BTCUSDT, so every symbol's quant evidence silently came from BTC history.
This router makes evidence calculation factually symbol-specific:

    symbol -> MultiStrategyAlpha (own MarketDataEngine, own factual candles)

Rules enforced here:
  - NO cross-symbol indicator reuse and NO BTC fallback for other symbols.
  - Warmup uses only factual, closed OKX candles (feed.warmup). No synthetic
    warmup. If history is insufficient, the affected tools report
    data_quality=UNAVAILABLE while other evidence continues (§27/§28) — a
    missing factor never blocks DeepSeek (FACTOR_REQUIRED_FOR_TRADE = FALSE).
  - BTCUSDT's pre-existing engine (if any) is preserved unchanged.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from time import monotonic
from typing import Any

from crypto_trader.alpha.ensemble import MultiStrategyAlpha
from crypto_trader.strategy.base import StrategyContext

_UNAVAILABLE_EVIDENCE = {
    "regime": "UNKNOWN",
    "data_quality": "UNAVAILABLE",
    "source_refs": [],
    "features": {},
    "unavailable_reason": "EVIDENCE_ENGINE_UNAVAILABLE",
}


class PerSymbolEvidenceRouter:
    """Duck-types the MultiStrategyAlpha evidence surface, per symbol."""

    name = "per_symbol_evidence_router"

    def __init__(
        self,
        *,
        feed=None,
        alpha_params: dict[str, Any] | None = None,
        warmup_bars: int = 300,
        warmup_interval: str = "1m",
        max_engines: int = 40,
    ) -> None:
        self._feed = feed
        self._alpha_params = dict(alpha_params or {})
        self._warmup_bars = int(warmup_bars)
        self._warmup_interval = warmup_interval
        self._max_engines = max(0, int(max_engines))
        self._engines: OrderedDict[str, MultiStrategyAlpha] = OrderedDict()
        self._last_refresh: dict[str, float] = {}
        self._refresh_lock = asyncio.Lock()
        self._warmup_attempted: set[str] = set()
        self.stats = {
            "engines_created": 0,
            "warmups_ok": 0,
            "warmups_failed": 0,
            "resolve_misses": 0,
        }

    # ----------------------------------------------------------------- admin
    @property
    def symbol(self) -> str:
        # Protocol compatibility; the router itself is not symbol-bound.
        return next(iter(self._engines), "BTCUSDT")

    def register_existing(self, symbol: str, engine: MultiStrategyAlpha) -> None:
        """Adopt an already-warmed engine (e.g. the bootstrap BTC instance)."""
        self._engines[symbol] = engine
        self._warmup_attempted.add(symbol)

    def known_symbols(self) -> list[str]:
        return sorted(self._engines)

    def get(self, symbol: str) -> MultiStrategyAlpha | None:
        """Existing engine only — no creation, no I/O."""
        return self._engines.get(symbol)

    # ---------------------------------------------------------------- resolve
    async def resolve(self, symbol: str) -> MultiStrategyAlpha | None:
        """Return the factual per-symbol engine, creating+warming it once.

        Returns None only when the symbol cannot be honored at all. A failed
        warmup still yields an engine (tools honestly report UNAVAILABLE
        quality) — insufficient history never blocks other evidence (§27).
        """
        engine = self._engines.get(symbol)
        if engine is not None:
            self._engines.move_to_end(symbol)
            await self._refresh(symbol, engine)
            return engine
        if self._max_engines == 0:
            self.stats["resolve_misses"] += 1
            return None
        if len(self._engines) >= self._max_engines:
            evicted, _ = self._engines.popitem(last=False)
            self._warmup_attempted.discard(evicted)
            self._last_refresh.pop(evicted, None)
        engine = MultiStrategyAlpha(symbol=symbol, **self._alpha_params)
        self._engines[symbol] = engine
        self.stats["engines_created"] += 1
        await self._refresh(symbol, engine)
        return engine

    async def _refresh(self, symbol: str, engine: MultiStrategyAlpha) -> None:
        if self._feed is None or not hasattr(self._feed, "warmup"):
            return
        async with self._refresh_lock:
            if monotonic() - self._last_refresh.get(symbol, float("-inf")) < 30:
                return
            self._last_refresh[symbol] = monotonic()
            try:
                loaded = await asyncio.wait_for(
                    self._feed.warmup(
                        engine.mde, symbol, bars=self._warmup_bars,
                        interval=self._warmup_interval,
                    ), timeout=10,
                )
                self.stats["warmups_ok" if loaded else "warmups_failed"] += 1
            except Exception:
                self.stats["warmups_failed"] += 1

    async def run_forever(self) -> None:
        """Advance resident candle histories even when Chief selects no indicators."""
        while True:
            for symbol, engine in list(self._engines.items()):
                await self._refresh(symbol, engine)
            await asyncio.sleep(5)

    # ------------------------------------------------------- evidence surface
    def analyze_evidence(self, ctx: StrategyContext) -> dict:
        """Sync evidence for the ctx symbol (existing engines only)."""
        engine = self._engines.get(ctx.symbol)
        if engine is None:
            return dict(_UNAVAILABLE_EVIDENCE)
        return engine.analyze_evidence(ctx)

    async def analyze_tool(self, ctx: StrategyContext, name: str) -> dict:
        """Async tool analysis used by the router-aware tool registry."""
        engine = await self.resolve(ctx.symbol)
        if engine is None:
            return dict(_UNAVAILABLE_EVIDENCE)
        return engine.analyze_tool(ctx, name)

    async def shutdown(self) -> None:
        return None
