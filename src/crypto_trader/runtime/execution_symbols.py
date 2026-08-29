"""Canonical execution-symbol resolver for PAPER perpetual trading.

CORE_TRADING_DOCTRINE_V1 stays intact: real market data (BTCUSDT) describes the
market, strategies interpret it, the LLM proposes, RiskEngine authorizes. This
module only separates the EXECUTION contract symbol from the REFERENCE market
symbol so the runtime never confuses the two.
"""

from __future__ import annotations

PAPER_PERPETUAL_EXECUTION_SYMBOL = "BTCUSDT_PERP"
PAPER_PERPETUAL_REFERENCE_SYMBOL = "BTCUSDT"

# Generic PAPER-perpetual registry: every reference symbol listed here is
# executed through its own bidirectional paper perpetual contract
# (<REF>_PERP) backed by the REAL OKX reference market (spot book / ticker).
# The registry is data-driven: no per-symbol engines, no per-symbol paths.
PAPER_PERPETUAL_REFERENCE_SYMBOLS: tuple[str, ...] = (
    PAPER_PERPETUAL_REFERENCE_SYMBOL,
    "HYPEUSDT",
    "ZECUSDT",
    "ENAUSDT",
    "WLDUSDT",
    "ONDOUSDT",
    "FILUSDT",
    "TAOUSDT",
    "AAVEUSDT",
    "XLMUSDT",
    "HBARUSDT",
)

_PERP_TO_REFERENCE = {
    f"{reference}_PERP": reference for reference in PAPER_PERPETUAL_REFERENCE_SYMBOLS
}


def reference_symbol_for(execution_or_market_symbol: str) -> str:
    """Return the real-market symbol whose book/prices back this symbol.

    <REF>_PERP -> REF (mark/entry/exit/RiskEngine notional) for every
    registered paper-perpetual contract. Any other symbol is already a
    real-market reference symbol.
    """
    return _PERP_TO_REFERENCE.get(execution_or_market_symbol, execution_or_market_symbol)


def execution_symbol_for(reference_symbol: str) -> str:
    """Return the PAPER execution contract for a real-market reference.

    Registered references map to their bidirectional paper perpetual
    (<REF>_PERP). Other symbols remain their own spot reference (spot shorts
    stay protected by the RiskEngine SPOT_OVERSHORT gate).
    """
    if reference_symbol in PAPER_PERPETUAL_REFERENCE_SYMBOLS:
        return f"{reference_symbol}_PERP"
    return reference_symbol


def is_paper_perpetual_symbol(symbol: str) -> bool:
    return symbol in _PERP_TO_REFERENCE
