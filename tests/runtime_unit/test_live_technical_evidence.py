from __future__ import annotations

import pytest

from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.runtime.live_decision_context import LiveDecisionContextProvider


def _candles(count: int = 220) -> list[dict]:
    rows = []
    for i in range(count):
        close = 100 + i * 0.1 + ((i % 9) - 4) * 0.03
        rows.append({
            "timestamp": f"2026-08-28T00:{i % 60:02d}:00+00:00",
            "open": str(close - 0.05),
            "high": str(close + 0.4),
            "low": str(close - 0.4),
            "close": str(close),
            "volume": str(1000 + i),
        })
    return rows


@pytest.mark.asyncio
async def test_live_bundle_embeds_advisory_technical_indicators():
    async def provider(symbol: str):
        return _candles()

    context_provider = LiveDecisionContextProvider(
        candle_provider=provider,
        symbol="BTCUSDT",
        candle_cache_seconds=60,
    )
    bundle = await context_provider.build(
        {"funding_rate": "0.0001", "open_interest": "10000"},
        symbol="BTCUSDT",
    )

    assert bundle is not None
    assert bundle.technical_indicators["authority"] == "ADVISORY"
    assert bundle.factor_snapshot["technical_indicator_authority"] == "ADVISORY"
    assert bundle.factor_snapshot["technical_indicators"]["indicators"]["rsi_14"] is not None

    chief = ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={},
        regime="UNKNOWN",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        factor_snapshot=bundle.factor_snapshot,
        strategy_evidence=bundle.evidence,
    )
    model_context = chief.domain_model_context()
    assert model_context["FactorSnapshot"]["technical_indicators"]["authority"] == "ADVISORY"
