from decimal import Decimal

from fastapi.testclient import TestClient

from crypto_trader.api.app import create_app
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType
from crypto_trader.ledger.service import LedgerPosting, LedgerService
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import OrderManager
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.lease import LeaseManager


def make_state(database):
    settings = Settings(app_env="test", trading_mode="PAPER", database_url=database.url)
    state = AppState(
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
    return state


async def test_api_health_and_ready(database):
    state = make_state(database)
    client = TestClient(create_app(state))
    assert client.get("/health").status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["mode"] == "PAPER"
    runtime = client.get("/runtime")
    assert runtime.status_code == 200
    assert runtime.json()["engine"] == "not attached"


async def test_api_financial_endpoints_return_strings_not_floats(database):
    state = make_state(database)
    await state.ledger.record(
        LedgerEntryType.DEPOSIT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("1000.1")),
            LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("1000.1")),
        ],
        transaction_id="txn_api_deposit",
    )
    await state.portfolio.refresh(initial_balances={"USDT": Decimal("0")})
    await state.audit.log("TEST_API", target="x", run_id="run_x")
    client = TestClient(create_app(state))

    account = client.get("/account").json()
    assert account["balances"]["USDT"]["total"] == "1000.1"

    ledger = client.get("/ledger").json()
    assert ledger[0]["amount"] == "1000.1"
    assert isinstance(ledger[0]["amount"], str)

    audit = client.get("/audit").json()
    assert any(row["action"] == "TEST_API" for row in audit)


async def test_api_version_endpoint(database):
    state = make_state(database)
    client = TestClient(create_app(state))
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json()["api_version"] == "v1"
    assert response.json()["environment"] == "test"


async def test_api_killswitch_route(database):
    state = make_state(database)
    client = TestClient(create_app(state))
    assert client.get("/killswitch").json()["enabled"] is False
    response = client.post("/killswitch", json={"enabled": True, "reason": "api test"})
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert state.risk.kill_switch.enabled is True
