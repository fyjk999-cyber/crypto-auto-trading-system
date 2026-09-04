from __future__ import annotations

import pytest

from crypto_trader.universe.okx_registry import OKXMarketUniverse


class InstrumentClient:
    async def get_instruments(self, instrument_type: str):
        values = {
            "SPOT": [
                {
                    "instId": "BTC-USDT",
                    "instType": "SPOT",
                    "baseCcy": "BTC",
                    "quoteCcy": "USDT",
                    "tickSz": "0.1",
                    "lotSz": "0.00001",
                    "minSz": "0.00001",
                    "state": "live",
                    "listTime": "1722470400000",
                }
            ],
            "SWAP": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "instType": "SWAP",
                    "baseCcy": "BTC",
                    "quoteCcy": "USDT",
                    "settleCcy": "USDT",
                    "ctVal": "0.01",
                    "ctMult": "1",
                    "tickSz": "0.1",
                    "lotSz": "1",
                    "minSz": "1",
                    "state": "live",
                }
            ],
            "FUTURES": [
                {
                    "instId": "BTC-USDT-250627",
                    "instType": "FUTURES",
                    "baseCcy": "BTC",
                    "quoteCcy": "USDT",
                    "settleCcy": "USDT",
                    "ctVal": "0.01",
                    "ctMult": "1",
                    "tickSz": "0.1",
                    "lotSz": "1",
                    "minSz": "1",
                    "state": "live",
                }
            ],
        }
        return values[instrument_type]


async def test_dynamic_okx_registry_keeps_market_layers_explicit():
    registry = OKXMarketUniverse(InstrumentClient())
    discovered = await registry.discover()

    assert {item.instrument_type for item in discovered} == {"SPOT", "SWAP", "FUTURES"}
    assert {item.instrument_id for item in registry.layer("ALL_MARKET")} == {
        "BTC-USDT",
        "BTC-USDT-SWAP",
        "BTC-USDT-250627",
    }
    assert registry.layer("EXECUTABLE") == []

    registry.set_observable("BTC-USDT-SWAP", factual_data_fresh=True)
    registry.set_analysis("BTC-USDT-SWAP", allowed=True)
    registry.set_executable("BTC-USDT-SWAP", compatible=True)

    assert [item.instrument_id for item in registry.layer("OBSERVABLE")] == ["BTC-USDT-SWAP"]
    assert [item.instrument_id for item in registry.layer("ANALYSIS")] == ["BTC-USDT-SWAP"]
    assert [item.instrument_id for item in registry.layer("EXECUTABLE")] == ["BTC-USDT-SWAP"]
    assert registry.layer("ALL_MARKET")[1].contract_value is not None


async def test_non_observable_market_cannot_be_analysis_or_executable():
    registry = OKXMarketUniverse(InstrumentClient())
    await registry.discover()

    registry.set_analysis("BTC-USDT", allowed=True)
    registry.set_executable("BTC-USDT", compatible=True)
    assert registry.layer("ANALYSIS") == []
    assert registry.layer("EXECUTABLE") == []
    with pytest.raises(KeyError):
        registry.set_observable("ETH-USDT-SWAP", factual_data_fresh=True)
