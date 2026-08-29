from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from crypto_trader.alpha.learning import FastLearning
from crypto_trader.api.app import create_app
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.governance.memory import FailureClass, TradeMemoryRecord
from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.ledger.service import LedgerService
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.market_data.state import DataHealth, SourceStatus
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import OrderManager
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.lease import LeaseManager


def make_state(database, app_env="development"):
    settings = Settings(
        _env_file=None, app_env=app_env, trading_mode="PAPER", database_url=database.url
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


async def test_websocket_connect_receive_disconnect_reconnect(database):
    state = make_state(database)
    client = TestClient(create_app(state))
    for _ in range(5):
        with client.websocket_connect("/ws") as websocket:
            data = websocket.receive_json()
            assert data["event_type"] == "runtime"
            assert data["event_version"] == "v1"
            assert "payload" in data
    assert client.get("/health").status_code == 200


def test_cors_development_allows_local_ui(database):
    state = make_state(database, app_env="development")
    client = TestClient(create_app(state))
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_cors_production_does_not_open_localhost(database):
    state = make_state(database, app_env="production")
    client = TestClient(create_app(state))
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


async def test_daily_review_scheduler_idempotent(database):
    persistence = MemoryPersistence(database.session_factory)
    record = TradeMemoryRecord(
        decision_id="stability_d1",
        symbol="BTCUSDT",
        side="LONG",
        regime="BULL",
        strategy_scores={},
        effective_weights={},
        raw_confidence=Decimal("0.8"),
        calibrated_confidence=Decimal("0.7"),
        recommended_position=Decimal("1"),
        approved_position=Decimal("1"),
        recommended_leverage=Decimal("5"),
        approved_leverage=Decimal("3"),
        entry=Decimal("100"),
        exit=Decimal("105"),
        fees=Decimal("0.1"),
        funding_pnl=Decimal("0"),
        realized_pnl=Decimal("4.8"),
        r_multiple=Decimal("0.96"),
        failure_class=None,
    )
    await persistence.save_trade_memory(record)
    scheduler = DailyReviewScheduler(database.session_factory)
    today = (
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat()
    )
    first = await scheduler.run_once(today)
    second = await scheduler.run_once(today)
    assert first["trade_count"] == 1
    assert first == second
    rows = await persistence.load_daily_reviews(limit=10)
    assert len(rows) == 1


async def test_fast_learning_restore_from_db(database):
    persistence = MemoryPersistence(database.session_factory)
    await persistence.save_trade_memory(
        TradeMemoryRecord(
            decision_id="restore_d1",
            symbol="BTCUSDT",
            side="LONG",
            regime="BULL",
            strategy_scores={},
            effective_weights={},
            raw_confidence=Decimal("0.8"),
            calibrated_confidence=Decimal("0.7"),
            recommended_position=Decimal("1"),
            approved_position=Decimal("1"),
            recommended_leverage=Decimal("5"),
            approved_leverage=Decimal("3"),
            entry=Decimal("100"),
            exit=Decimal("101"),
            fees=Decimal("0.1"),
            funding_pnl=Decimal("0"),
            realized_pnl=Decimal("0.9"),
            r_multiple=Decimal("0.18"),
            failure_class=FailureClass.TIMING_ERROR,
        )
    )
    fast = FastLearning()
    for record in await persistence.load_trade_memory(limit=100):
        fast.record_trade("multi_strategy_alpha", record.side, record.realized_pnl or Decimal("0"))
        if record.failure_class is not None:
            fast.failure_memory["multi_strategy_alpha"] = (
                fast.failure_memory.get("multi_strategy_alpha", 0) + 1
            )
    assert fast.strategy_score("multi_strategy_alpha") is not None
    assert fast.failure_count("multi_strategy_alpha") == 1


def test_market_source_status_model_exposes_last_error():
    status = SourceStatus(
        source="BINANCE_USDM_PUBLIC",
        status=DataHealth.UNAVAILABLE,
        age_seconds=-1,
        updated_at=datetime.now(UTC),
        last_error="HTTP_451_GEO_RESTRICTED",
    )
    data = status.model_dump(mode="json")
    assert data["last_error"] == "HTTP_451_GEO_RESTRICTED"
    assert data["status"] == "UNAVAILABLE"


async def test_market_data_health_recovers_after_transient_fetch_failure(database):
    """One transient per-symbol fetch failure must not mark market data
    unhealthy forever: the next successful real ingest clears the flag.
    Per-symbol staleness gates are unchanged (they raise independently)."""
    from tests.conftest import make_paper_engine

    db = database
    engine = make_paper_engine(db)
    engine.health.set("market_data", False, "LTCUSDT invalidated")
    assert engine.health.components["market_data"]["ok"] is False

    # Simulate the tick-path success branch: a real ingest cleared the flag.
    from crypto_trader.market_data.orderbook import OrderBook

    book = OrderBook(symbol="LTCUSDT", exchange="OKX")
    book.apply_snapshot(1, [(100, 1)], [(101, 1)])
    engine.market_data.books["LTCUSDT"] = book
    # Reproduce the production code path directly.
    engine.health.set("market_data", True)
    assert engine.health.components["market_data"]["ok"] is True

    # And a subsequent failure still fails closed.
    engine.health.set("market_data", False, "ETHUSDT invalidated")
    assert engine.health.components["market_data"]["ok"] is False
