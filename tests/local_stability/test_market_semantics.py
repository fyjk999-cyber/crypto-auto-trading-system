from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from crypto_trader.api.app import create_app
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.domain.errors import MarketDataUnhealthy
from crypto_trader.exchange.binance_futures_public import BinancePublicDataUnavailable
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


async def test_real_market_unavailable_reports_binance_not_synthetic(database):
    client = TestClient(create_app(make_state(database, "PAPER_REAL_MARKET")))
    data = client.get("/market").json()
    assert data["provider"] == "BINANCE_USDM"
    assert data["status"] == "UNAVAILABLE"


async def test_real_market_adapter_does_not_silent_fallback():
    class FailingPublicClient:
        async def get_orderbook(self, symbol, limit=100):
            raise BinancePublicDataUnavailable("HTTP_451_GEO_RESTRICTED")

    adapter = PaperRealMarketAdapter(
        initial_balances={"USDT": Decimal("100000")},
    )
    adapter.public_client = FailingPublicClient()
    await adapter.connect()
    with pytest.raises(MarketDataUnhealthy):
        await adapter.get_orderbook("BTCUSDT")


async def test_klines_geo_restricted_status(database, monkeypatch):
    from crypto_trader.exchange.binance_futures_public import BinanceUSDMFuturesPublicClient

    async def fail_get_klines(self, symbol, interval="1m", limit=500):
        raise BinancePublicDataUnavailable("HTTP_451_GEO_RESTRICTED")

    monkeypatch.setattr(BinanceUSDMFuturesPublicClient, "get_klines", fail_get_klines)
    client = TestClient(create_app(make_state(database, "PAPER_REAL_MARKET")))
    data = client.get("/market/klines?symbol=BTCUSDT&interval=1m&limit=100").json()
    assert data["source"] == "BINANCE_USDM"
    assert data["status"] == "GEO_RESTRICTED"
    assert data["candles"] == []
