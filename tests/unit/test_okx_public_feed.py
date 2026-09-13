from __future__ import annotations

from crypto_trader.exchange.okx import OKXDiagnosticError
from crypto_trader.market_data.okx_public_feed import OKXPublicMarketFeed
from crypto_trader.market_data.state import DataHealth


class FactualOKX:
    async def get_orderbook(self, symbol: str):
        assert symbol == "BTC-USDT-SWAP"
        return {
            "data": [
                {"ts": "1722470400000", "bids": [["60000", "2"]], "asks": [["60001", "3"]]}
            ]
        }

    async def get_mark_price(self, symbol: str):
        assert symbol == "BTC-USDT-SWAP"
        return {
            "mark_price": "60000.5",
            "index_price": "59999.5",
            "funding_rate": "0.0001",
            "next_funding_time": None,
        }

    async def get_open_interest(self, symbol: str):
        assert symbol == "BTC-USDT-SWAP"
        return {"open_interest": "12345", "open_interest_ccy": "0"}

    async def disconnect(self):
        return None


class FailedOKX(FactualOKX):
    async def get_orderbook(self, symbol: str):
        raise OKXDiagnosticError("NETWORK_ERROR", "network unavailable")


async def test_okx_public_feed_uses_only_matching_symbol_with_provenance():
    state = await OKXPublicMarketFeed(client=FactualOKX()).refresh("BTCUSDT")

    assert state.symbol == "BTCUSDT"
    assert state.source == "OKX_PUBLIC"
    assert state.exchange == "OKX"
    assert str(state.price) == "60000.5"
    assert str(state.mark_price) == "60000.5"
    assert str(state.index_price) == "59999.5"
    assert str(state.open_interest) == "12345"
    assert state.health == DataHealth.HEALTHY
    assert {source.source for source in state.sources.values()} == {"OKX_PUBLIC"}


async def test_okx_public_feed_does_not_substitute_price_when_orderbook_fails():
    state = await OKXPublicMarketFeed(client=FailedOKX()).refresh("BTCUSDT")

    assert state.sources["orderbook"].status == DataHealth.UNAVAILABLE
    assert state.price == 0
    assert state.health in {DataHealth.DEGRADED, DataHealth.UNAVAILABLE}
