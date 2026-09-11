"""V7 final closure: derivative contract metadata must fail closed."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from crypto_trader.exchange.okx import OKXAdapter
from crypto_trader.simulator.real_market_paper import PaperRealMarketAdapter


def _valid_row(**overrides):
    row = {
        "instId": "BTC-USDT-SWAP",
        "instType": "SWAP",
        "ctType": "linear",
        "ctVal": "0.01",
        "ctMult": "1",
        "ctValCcy": "BTC",
        "settleCcy": "USDT",
        "tickSz": "0.1",
        "lotSz": "0.01",
        "minSz": "0.01",
        "state": "live",
    }
    row.update(overrides)
    return row


@pytest.fixture()
def paper_adapter():
    return PaperRealMarketAdapter(initial_balances={"USDT": Decimal("1000")})


def test_valid_linear_usdt_swap_preserves_exact_ctval_ctmult(paper_adapter):
    instrument = paper_adapter._instrument_from_okx_row(_valid_row())
    assert instrument is not None
    assert instrument.symbol == "BTCUSDT"
    assert instrument.instrument_type == "LINEAR_PERP"
    assert instrument.contract_size == Decimal("0.01")
    assert instrument.contract_multiplier == Decimal("1")
    assert instrument.ct_val == "0.01"
    assert instrument.ct_mult == "1"
    assert instrument.ct_type == "linear"


@pytest.mark.parametrize("value", [None, "", "bad", "0", "-0.01"])
def test_swap_invalid_ctval_is_rejected(paper_adapter, value):
    row = _valid_row()
    if value is None:
        row.pop("ctVal")
    else:
        row["ctVal"] = value
    assert paper_adapter._instrument_from_okx_row(row) is None


@pytest.mark.parametrize("value", [None, "", "bad", "0", "-1"])
def test_swap_invalid_ctmult_is_rejected(paper_adapter, value):
    row = _valid_row()
    if value is None:
        row.pop("ctMult")
    else:
        row["ctMult"] = value
    assert paper_adapter._instrument_from_okx_row(row) is None


@pytest.mark.parametrize("value", [None, "", "inverse", "option"])
def test_swap_missing_or_non_linear_cttype_is_rejected(paper_adapter, value):
    row = _valid_row()
    if value is None:
        row.pop("ctType")
    else:
        row["ctType"] = value
    assert paper_adapter._instrument_from_okx_row(row) is None


def test_missing_ctmult_is_not_defaulted_to_one(paper_adapter):
    assert paper_adapter._instrument_from_okx_row(
        _valid_row(ctMult=None)
    ) is None
    # Explicit provider "1" is different from missing.
    instrument = paper_adapter._instrument_from_okx_row(_valid_row(ctMult="1"))
    assert instrument is not None
    assert instrument.contract_multiplier == Decimal("1")


def test_missing_ctval_is_not_defaulted_to_one(paper_adapter):
    assert paper_adapter._instrument_from_okx_row(
        _valid_row(ctVal=None)
    ) is None
    instrument = paper_adapter._instrument_from_okx_row(_valid_row(ctVal="1"))
    assert instrument is not None
    assert instrument.contract_size == Decimal("1")


class _ExchangeStub:
    def __init__(self, rows):
        self.rows = rows

    async def get_instruments(self, instrument_type):
        return self.rows if instrument_type == "SWAP" else []


async def test_okx_adapter_exchange_info_excludes_unproven_derivatives():
    valid = _valid_row(instId="BTC-USDT-SWAP")
    missing_mult = _valid_row(instId="ETH-USDT-SWAP", ctMult=None)
    missing_cy = _valid_row(instId="SOL-USDT-SWAP", ctType=None)
    stub = _ExchangeStub([valid, missing_mult, missing_cy])
    instruments = await OKXAdapter.get_exchange_info(stub, None)
    by_symbol = {item.symbol: item for item in instruments}
    assert "BTCUSDT" in by_symbol
    assert by_symbol["BTCUSDT"].contract_size == Decimal("0.01")
    assert by_symbol["BTCUSDT"].contract_multiplier == Decimal("1")
    assert "ETHUSDT" not in by_symbol
    assert "SOLUSDT" not in by_symbol


async def test_paper_real_market_registry_contains_only_proven_linear_swaps():
    class FakeClient:
        def __init__(self, rows):
            self.rows = rows

        async def get_instruments(self, instrument_type):
            return self.rows

    feed = SimpleNamespace(client=FakeClient([_valid_row(ctMult=None)]))
    adapter = PaperRealMarketAdapter(
        initial_balances={"USDT": Decimal("1000")}, feed=feed
    )
    assert await adapter.get_exchange_info("BTCUSDT") == []
    # Only the base simulated SPOT default remains; no unproven perp entered.
    assert adapter.instruments["BTCUSDT"].instrument_type == "SPOT"

    feed.client = FakeClient([_valid_row()])
    instruments = await adapter.get_exchange_info("BTCUSDT")
    assert len(instruments) == 1
    assert instruments[0].instrument_type == "LINEAR_PERP"
    assert instruments[0].contract_size == Decimal("0.01")
    assert instruments[0].contract_multiplier == Decimal("1")


async def test_build_system_paper_real_market_rejects_unproven_instrument(
    database, monkeypatch
):
    import crypto_trader.simulator.real_market_paper as real_market_paper
    from crypto_trader.config import Settings
    from crypto_trader.runtime.bootstrap import build_system

    class FakeClient:
        def __init__(self):
            self.rows = [_valid_row(ctMult=None)]

        async def get_instruments(self, instrument_type):
            return self.rows

    class FakeFeed:
        def __init__(self, symbol="BTCUSDT"):
            self.client = FakeClient()

        async def warmup(self, *args, **kwargs):
            return None

    monkeypatch.setattr(real_market_paper, "OKXPublicMarketFeed", FakeFeed)
    bundle = await build_system(
        Settings(
            _env_file=None,
            app_env="test",
            trading_mode="PAPER",
            live_trading_enabled=False,
            database_url=database.url,
            auto_start_runtime=False,
            paper_mode="PAPER_REAL_MARKET",
            opportunity_scan_enabled=False,
        )
    )
    try:
        adapter = bundle.engine.adapter
        assert isinstance(adapter, real_market_paper.PaperRealMarketAdapter)
        # Missing ctMult: row excluded from the executable registry.
        assert await adapter.get_exchange_info("BTCUSDT") == []
        assert "BTCUSDT" not in {
            symbol
            for symbol, instrument in adapter.instruments.items()
            if instrument.instrument_type == "LINEAR_PERP"
        }

        # Explicit ctVal/ctMult: exact values enter the registry.
        adapter.feed.client.rows = [_valid_row()]
        instruments = await adapter.get_exchange_info("BTCUSDT")
        assert len(instruments) == 1
        assert instruments[0].instrument_type == "LINEAR_PERP"
        assert instruments[0].contract_size == Decimal("0.01")
        assert instruments[0].contract_multiplier == Decimal("1")
    finally:
        await bundle.database.close()


def test_missing_ctval_never_becomes_contract_spec_proven():
    # Source review guard: parser returns None, so no Instrument can reach
    # ContractSpecProvenance or FundingAccountingSupervisor with spec=1.
    adapter = PaperRealMarketAdapter(
        initial_balances={"USDT": Decimal("1000")}
    )
    assert adapter._instrument_from_okx_row(_valid_row(ctVal=None)) is None
    assert adapter._instrument_from_okx_row(_valid_row(ctMult=None)) is None
