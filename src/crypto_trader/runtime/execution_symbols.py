"""Canonical execution-symbol resolver for PAPER perpetual trading.

CORE_TRADING_DOCTRINE_V1 stays intact: real market data (BTCUSDT) describes the
market, strategies interpret it, the LLM proposes, RiskEngine authorizes. This
module only separates the EXECUTION contract symbol from the REFERENCE market
symbol so the runtime never confuses the two.
"""

from __future__ import annotations

PAPER_PERPETUAL_EXECUTION_SYMBOL = "BTCUSDT_PERP"
PAPER_PERPETUAL_REFERENCE_SYMBOL = "BTCUSDT"

_PERP_TO_REFERENCE = {
    PAPER_PERPETUAL_EXECUTION_SYMBOL: PAPER_PERPETUAL_REFERENCE_SYMBOL,
}


def reference_symbol_for(execution_or_market_symbol: str) -> str:
    """Return the real-market symbol whose book/prices back this symbol.

    BTCUSDT_PERP -> BTCUSDT (mark/entry/exit/RiskEngine notional).
    Any other symbol is already a real-market reference symbol.
    """
    return _PERP_TO_REFERENCE.get(execution_or_market_symbol, execution_or_market_symbol)


def execution_symbol_for(reference_symbol: str) -> str:
    """Return the PAPER execution contract for a real-market reference.

    BTCUSDT -> BTCUSDT_PERP (bidirectional LONG/SHORT paper perpetual).
    Other symbols remain their own spot reference (the paper perpetual engine
    is BTC-only today).
    """
    if reference_symbol == PAPER_PERPETUAL_REFERENCE_SYMBOL:
        return PAPER_PERPETUAL_EXECUTION_SYMBOL
    return reference_symbol


def is_paper_perpetual_symbol(symbol: str) -> bool:
    return symbol == PAPER_PERPETUAL_EXECUTION_SYMBOL
