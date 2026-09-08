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
        self._max_engines = int(max_engines)
        self._engines: dict[str, MultiStrategyAlpha] = {}
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
            return engine
        if len(self._engines) >= self._max_engines:
            self.stats["resolve_misses"] += 1
            return None
        engine = MultiStrategyAlpha(symbol=symbol, **self._alpha_params)
        self._engines[symbol] = engine
        self.stats["engines_created"] += 1
        if symbol not in self._warmup_attempted:
            self._warmup_attempted.add(symbol)
            if self._feed is not None and hasattr(self._feed, "warmup"):
                try:
                    await self._feed.warmup(
                        engine.mde, symbol, bars=self._warmup_bars, interval=self._warmup_interval
                    )
                    self.stats["warmups_ok"] += 1
                except Exception:
                    # Factual warmup failure is explicit at the feed; keep the
                    # engine but let tools report their real data quality.
                    self.stats["warmups_failed"] += 1
        return engine

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
