from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from crypto_trader.api.app import create_app
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.domain.errors import MarketDataUnhealthy
from crypto_trader.exchange.binance_futures_public import BinancePublicDataUnavailable
from crypto_trader.exchange.okx import OKXAdapter, OKXDiagnosticError
from crypto_trader.ledger.service import LedgerService
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import OrderManager
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.lease import LeaseManager
from crypto_trader.simulator.real_market_paper import PaperRealMarketAdapter


def make_state(database, paper_mode):
    settings = Settings(
        _env_file=None,
        app_env="development",
        trading_mode="PAPER",
        database_url=database.url,
        paper_mode=paper_mode,
    )
    return AppState(
        settings=settings,
        database=database,
        order_manager=OrderManager(database.session_factory),
        ledger=LedgerService(database.session_factory),
        portfolio=PortfolioService(database.session_factory),
        audit=AuditService(database.session_factory),
        risk=RiskEngine(),
        market_data=MarketDataService(),
        leases=LeaseManager(database.session_factory),
        reconciliation=ReconciliationService(database.session_factory),
    )


def test_default_paper_uses_real_market():
    settings = Settings(_env_file=None)
    assert settings.paper_mode == "PAPER_REAL_MARKET"


def test_start_script_sets_real_market():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "scripts" / "start-paper.sh").read_text()
    assert "PAPER_MODE=PAPER_REAL_MARKET" in text
    assert "Market Data Mode: PAPER_REAL_MARKET" in text


async def test_synthetic_requires_explicit_mode_and_never_reports_binance(database):
    client = TestClient(create_app(make_state(database, "PAPER_SYNTHETIC")))
    data = client.get("/market").json()
    assert data["provider"] == "SYNTHETIC"
    assert "BINANCE" not in data["source"]


async def test_real_market_unavailable_reports_okx_not_synthetic(database):
    client = TestClient(create_app(make_state(database, "PAPER_REAL_MARKET")))
    data = client.get("/market").json()
    assert data["provider"] == "OKX"
    assert data["status"] == "UNAVAILABLE"


async def test_real_market_adapter_does_not_silent_fallback():
    class FailingPublicClient:
        async def get_orderbook(self, symbol, limit=100):
            raise RuntimeError("OKX unavailable")

    class FailingFeed:
        symbol = "BTCUSDT"
        client = FailingPublicClient()

    adapter = PaperRealMarketAdapter(
        initial_balances={"USDT": Decimal("100000")},
        feed=FailingFeed(),
    )
    await adapter.connect()
    with pytest.raises(MarketDataUnhealthy):
        await adapter.get_orderbook("BTCUSDT")


def test_paper_real_market_uses_okx_public_feed():
    adapter = PaperRealMarketAdapter(initial_balances={"USDT": Decimal("100000")})
    assert adapter.feed.__class__.__name__ == "OKXPublicMarketFeed"


async def test_okx_orderbook_is_normalized_to_canonical_symbol():
    class PublicClient:
        async def get_orderbook(self, symbol, limit=100):
            assert symbol == "BTC-USDT-SWAP"
            return {
                "data": [
                    {
                        "ts": "1722470400000",
                        "bids": [["100", "2", "0", "1"]],
                        "asks": [["101", "3", "0", "1"]],
                    }
                ]
            }

    class MockFeed:
        symbol = "BTCUSDT"
        client = PublicClient()

    adapter = PaperRealMarketAdapter(
        initial_balances={"USDT": Decimal("100000")},
        feed=MockFeed(),
    )
    book = await adapter.get_orderbook("BTCUSDT")
    assert book.symbol == "BTCUSDT"
    assert book.exchange == "OKX"
    assert book.best_bid().price == Decimal("100")
    assert book.best_ask().price == Decimal("101")


async def test_exchange_health_separates_okx_market_from_local_paper_execution(database):
    client = TestClient(create_app(make_state(database, "PAPER_REAL_MARKET")))
    data = client.get("/exchange-health").json()
    assert data["market_data"]["provider"] == "OKX"
    assert data["execution"]["provider"] == "LOCAL_PAPER"
    assert data["mode"] == "PAPER"


async def test_klines_use_okx_public_data_in_chronological_order(database, monkeypatch):
    async def candles(self, inst_id, bar, limit=500):
        assert inst_id == "BTC-USDT-SWAP"
        assert bar == "1H"
        return [
            ["1722470400000", "2", "3", "1", "2.5", "10", "0", "0", "1"],
            ["1722466800000", "1", "2", "0.5", "1.5", "9", "0", "0", "0"],
            ["1722470400000", "2", "3", "1", "2.6", "11", "0", "0", "1"],
        ]

    monkeypatch.setattr(OKXAdapter, "get_candles", candles)
    client = TestClient(create_app(make_state(database, "PAPER_REAL_MARKET")))
    data = client.get("/market/klines?symbol=BTCUSDT&interval=1h&limit=100").json()
    assert data["source"] == "OKX"
    assert data["status"] == "HEALTHY"
    assert data["provider_symbol"] == "BTC-USDT-SWAP"
    assert [row["close"] for row in data["candles"]] == ["1.5", "2.6"]
    assert data["candles"][0]["closed"] is False


async def test_okx_kline_failure_returns_empty_unavailable_data(database, monkeypatch):
    async def unavailable(self, inst_id, bar, limit=500):
        raise OKXDiagnosticError("NETWORK_ERROR", "Unable to connect to OKX")

    monkeypatch.setattr(OKXAdapter, "get_candles", unavailable)
    client = TestClient(create_app(make_state(database, "PAPER_REAL_MARKET")))
    data = client.get("/market/klines?symbol=BTCUSDT&interval=1m&limit=100").json()
    assert data["source"] == "OKX"
    assert data["status"] == "UNAVAILABLE"
    assert data["candles"] == []


async def test_binance_compatibility_branch_retains_geo_restricted_status(database, monkeypatch):
    from crypto_trader.exchange.binance_futures_public import BinanceUSDMFuturesPublicClient

    async def fail_get_klines(self, symbol, interval="1m", limit=500):
        raise BinancePublicDataUnavailable("HTTP_451_GEO_RESTRICTED")

    monkeypatch.setattr(BinanceUSDMFuturesPublicClient, "get_klines", fail_get_klines)
    state = make_state(database, "PAPER_REAL_MARKET")
    state.settings.kline_provider = "BINANCE"
    client = TestClient(create_app(state))
    data = client.get("/market/klines?symbol=BTCUSDT&interval=1m&limit=100").json()
    assert data["source"] == "BINANCE_USDM"
    assert data["status"] == "GEO_RESTRICTED"
    assert data["candles"] == []
