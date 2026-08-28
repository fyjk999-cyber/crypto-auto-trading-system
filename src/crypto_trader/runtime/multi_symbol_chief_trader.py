"""Round-robin multi-symbol wrapper for the canonical Chief Trader.

TradingEngine intentionally remains unchanged. It asks the first strategy for
its current ``symbol`` when building StrategyContext; this adapter rotates that
symbol across the configured universe one coin per engine tick. LLM decision
throttling is tracked per symbol so one BTC decision cannot suppress ETH/SOL
analysis for the next 60 seconds.
"""

from __future__ import annotations

import time

from crypto_trader.domain.models import SignalIntent
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.runtime.chief_trader_strategy import ChiefTraderStrategyAdapter
from crypto_trader.strategy.base import StrategyContext


class MultiSymbolChiefTraderStrategyAdapter(ChiefTraderStrategyAdapter):
    version = "2.1.0"

    def __init__(self, *, symbols: tuple[str, ...] | list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        mapper = SymbolMapper()
        normalized = tuple(mapper.to_canonical(symbol) for symbol in symbols)
        if not normalized:
            raise ValueError("multi-symbol Chief Trader requires at least one symbol")
        if len(normalized) != len(set(normalized)):
            raise ValueError("multi-symbol Chief Trader symbols must be unique")
        self.symbols = normalized
        self._symbol_cursor = 0
        self.last_scan_symbol = normalized[0]
        self._last_decision_completed_by_symbol: dict[str, float] = {}

    @property
    def symbol(self) -> str:
        """Return the next symbol for TradingEngine._strategy_context()."""
        current = self.symbols[self._symbol_cursor]
        self._symbol_cursor = (self._symbol_cursor + 1) % len(self.symbols)
        self.last_scan_symbol = current
        return current

    async def on_market_data(self, ctx: StrategyContext) -> list[SignalIntent]:
        # Keep the canonical fail-closed provider checks while making the
        # expensive-decision cadence independent for every coin.
        if self.provider is None or not self.provider.healthy():
            return []
        if not getattr(self.provider, "route_ready", lambda: True)():
            return []
        now = time.monotonic()
        last = self._last_decision_completed_by_symbol.get(ctx.symbol)
        if last is not None and now - last < self.min_decision_interval_seconds:
            return []
        try:
            return await self._decide(ctx)
        finally:
            self._last_decision_completed_by_symbol[ctx.symbol] = time.monotonic()

    async def _build_context(self, ctx: StrategyContext):
        # The base Chief Trader owns all decision/risk semantics. We only point
        # its real-data context provider at the coin currently being scanned.
        if self.decision_context_provider is not None:
            set_symbol = getattr(self.decision_context_provider, "set_symbol", None)
            if set_symbol is not None:
                set_symbol(ctx.symbol)
        return await super()._build_context(ctx)
