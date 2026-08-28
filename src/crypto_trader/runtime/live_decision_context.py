"""Live decision context: real FactorSnapshot + strategy evidence per symbol.

Wires the canonical factor system (FactorToolGateway.calculate_snapshot) and
StrategyEvidenceBuilder into the Live LLM decision context. The provider is
symbol-aware and keeps independent evidence builders so regime history cannot
leak between different coins. If real candles cannot be fetched, it returns
None and the entry path fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.factors.tool_gateway import FactorToolGateway
from crypto_trader.llm_chief.strategy_evidence import StrategyEvidenceBuilder


@dataclass
class LiveDecisionBundle:
    factor_snapshot_id: str
    factor_set_version: str
    factor_snapshot: dict
    evidence: dict  # StrategyEvidencePackage.to_dict()


class LiveDecisionContextProvider:
    def __init__(
        self,
        *,
        candle_provider,
        factor_gateway: FactorToolGateway | None = None,
        symbol: str = "BTCUSDT",
        min_candles: int = 30,
    ) -> None:
        """candle_provider: async (symbol) -> list[dict] oldest-first candles."""
        self.candle_provider = candle_provider
        self.factor_gateway = factor_gateway or FactorToolGateway()
        self.mapper = SymbolMapper()
        self.symbol = self.mapper.to_canonical(symbol)
        self.min_candles = min_candles
        self._evidence_builders: dict[str, StrategyEvidenceBuilder] = {}
        self.evidence_builder = self._builder_for(self.symbol)

    def _builder_for(self, symbol: str) -> StrategyEvidenceBuilder:
        builder = self._evidence_builders.get(symbol)
        if builder is None:
            builder = StrategyEvidenceBuilder(symbol=symbol)
            self._evidence_builders[symbol] = builder
        return builder

    def set_symbol(self, symbol: str) -> None:
        self.symbol = self.mapper.to_canonical(symbol)
        self.evidence_builder = self._builder_for(self.symbol)

    async def build(
        self,
        market_data: dict | None,
        symbol: str | None = None,
    ) -> LiveDecisionBundle | None:
        current_symbol = self.mapper.to_canonical(symbol) if symbol else self.symbol
        self.set_symbol(current_symbol)
        candles = await self.candle_provider(current_symbol)
        if not candles or len(candles) < self.min_candles:
            return None
        snapshot = self.factor_gateway.calculate_snapshot(
            symbol=current_symbol,
            timeframe="1m",
            candles=candles,
            market_data=market_data,
        )
        evidence = self._builder_for(current_symbol).build(
            candles, market_data, timestamp=datetime.now(UTC).isoformat()
        )
        return LiveDecisionBundle(
            factor_snapshot_id=snapshot.snapshot_id,
            factor_set_version=snapshot.factor_set_version,
            factor_snapshot=snapshot.to_dict(),
            evidence=evidence.model_dump(mode="json"),
        )
