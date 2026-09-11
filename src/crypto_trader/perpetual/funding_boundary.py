"""OKX venue boundary for funding public data.

Canonical symbols (BTCUSDT) live in TradePlan / Portfolio / Ledger /
FundingScope. Only this boundary translates to OKX instIds
(BTC-USDT-SWAP); OKX rows flow back without changing canonical identity.
"""

from __future__ import annotations

from crypto_trader.exchange.symbol_mapper import SymbolMapper


class FundingSymbolMappingError(ValueError):
    """Canonical instrument cannot be mapped to the OKX funding venue."""


class FundingPublicDataBoundary:
    def __init__(self, client, symbol_mapper: SymbolMapper | None = None) -> None:
        if isinstance(client, FundingPublicDataBoundary):
            client = client.client
        self.client = client
        self.symbol_mapper = symbol_mapper or SymbolMapper()

    def venue_symbol(self, canonical: str) -> str:
        if getattr(self.client, "expects_canonical_symbols", False):
            return canonical
        try:
            return self.symbol_mapper.to_okx(canonical)
        except ValueError as exc:
            raise FundingSymbolMappingError(
                f"funding venue mapping failed for {canonical}"
            ) from exc

    async def get_funding_rate_history(
        self,
        canonical_symbol: str,
        *,
        before: str | None = None,
        after: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        method = getattr(self.client, "get_funding_rate_history", None)
        if not callable(method):
            raise FundingSymbolMappingError(
                f"funding history client missing for {canonical_symbol}"
            )
        venue_symbol = (
            canonical_symbol
            if getattr(self.client, "expects_canonical_symbols", False)
            else self.venue_symbol(canonical_symbol)
        )
        return await method(
            venue_symbol, before=before, after=after, limit=limit
        )

    async def get_mark_price_candles(
        self,
        canonical_symbol: str,
        *,
        bar: str,
        limit: int = 100,
        before: str | None = None,
        after: str | None = None,
    ) -> list[list[str]]:
        method = getattr(self.client, "get_mark_price_candles", None)
        if not callable(method):
            raise FundingSymbolMappingError(
                f"mark-price candle client missing for {canonical_symbol}"
            )
        venue_symbol = (
            canonical_symbol
            if getattr(self.client, "expects_canonical_symbols", False)
            else self.venue_symbol(canonical_symbol)
        )
        return await method(
            venue_symbol, bar=bar, limit=limit, before=before, after=after
        )

    async def get_history_mark_price_candles(
        self,
        canonical_symbol: str,
        *,
        bar: str,
        limit: int = 100,
        before: str | None = None,
        after: str | None = None,
    ) -> list[list[str]]:
        method = getattr(self.client, "get_history_mark_price_candles", None)
        if not callable(method):
            raise FundingSymbolMappingError(
                f"history mark-price candle client missing for {canonical_symbol}"
            )
        venue_symbol = (
            canonical_symbol
            if getattr(self.client, "expects_canonical_symbols", False)
            else self.venue_symbol(canonical_symbol)
        )
        return await method(
            venue_symbol, bar=bar, limit=limit, before=before, after=after
        )


def as_funding_boundary(
    client, symbol_mapper: SymbolMapper | None = None
) -> FundingPublicDataBoundary | None:
    if client is None:
        return None
    if isinstance(client, FundingPublicDataBoundary):
        return client
    return FundingPublicDataBoundary(client, symbol_mapper=symbol_mapper)

