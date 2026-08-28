"""Live decision context: real FactorSnapshot + five-strategy evidence.

Wires the canonical factor system (FactorToolGateway.calculate_snapshot) and
the canonical alpha strategies into the Live LLM decision context. Replaces
the previous weak state (regime=UNKNOWN, quant_evidence=[], factor_intelligence
={}) whenever market data is available. Never fabricates data: if candles
cannot be fetched, returns None and the entry path fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

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
        self.symbol = symbol
        self.min_candles = min_candles
        self.evidence_builder = StrategyEvidenceBuilder(symbol=symbol)

    async def build(self, market_data: dict | None) -> LiveDecisionBundle | None:
        candles = await self.candle_provider(self.symbol)
        if not candles or len(candles) < self.min_candles:
            return None
        snapshot = self.factor_gateway.calculate_snapshot(
            symbol=self.symbol,
            timeframe="1m",
            candles=candles,
            market_data=market_data,
        )
        evidence = self.evidence_builder.build(
            candles, market_data, timestamp=datetime.now(UTC).isoformat()
        )
        return LiveDecisionBundle(
            factor_snapshot_id=snapshot.snapshot_id,
            factor_set_version=snapshot.factor_set_version,
            factor_snapshot=snapshot.to_dict(),
            evidence=evidence.model_dump(mode="json"),
        )
