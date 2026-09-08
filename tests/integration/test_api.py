from decimal import Decimal

from fastapi.testclient import TestClient

from crypto_trader.api.app import create_app, serialize_position
from crypto_trader.api.deps import AppState
from crypto_trader.config import Settings
from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType
from crypto_trader.domain.models import Position
from crypto_trader.ledger.service import LedgerPosting, LedgerService
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
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
    assert ready.json()["live_trading_enabled"] is False
    assert ready.json()["runtime"] is None
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


def test_position_api_uses_canonical_contract_size_exposure():
    payload = serialize_position(
        Position(
            symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            quantity=Decimal("-2"),
            avg_entry_price=Decimal("50000"),
            cost_basis=Decimal("1000"),
            instrument_type="LINEAR_PERP",
            contract_size=Decimal("0.01"),
            contract_multiplier=Decimal("1"),
        ),
        price=Decimal("51000"),
    )
    assert payload["gross_notional"] == "1020.00"
    assert payload["signed_notional"] == "-1020.00"
    assert payload["mark_price"] == "51000"
    assert payload["unrealized_pnl"] == "-20.00"
    assert payload["leverage"] == "1"


async def test_api_version_endpoint(database, monkeypatch):
    monkeypatch.setenv("RUNNING_SHA", "canonical-running-sha")
    state = make_state(database)
    client = TestClient(create_app(state))
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json()["api_version"] == "v1"
    assert response.json()["environment"] == "test"
    assert response.json()["git_sha"] == "canonical-running-sha"


async def test_api_exposes_sanitized_durable_llm_decision_lineage(database):
    state = make_state(database)
    await LLMDecisionStore(database.session_factory).save(
        ChiefTraderDecision(
            decision_id="llm-api-wait",
            symbol="BTCUSDT",
            action="WAIT",
            market_regime="RANGE",
            thesis="wait for factual breakout",
            model_provider="deepseek",
            model="deepseek-v4-pro",
        ),
        run_id="run-api",
        prompt_version="canonical-v1",
    )
    response = TestClient(create_app(state)).get("/llm/decisions")
    assert response.status_code == 200
    assert response.json()["count"] == 1
    decision = response.json()["decisions"][0]
    assert decision["decision_id"] == "llm-api-wait"
    assert decision["action"] == "WAIT"
    assert decision["model_provider"] == "deepseek"
    assert decision["trade_plan_id"] is None
    assert "api_key" not in str(response.json()).lower()

    signals = TestClient(create_app(state)).get("/signals")
    assert signals.status_code == 200
    assert signals.json()["quant_direct_trade_authority"] == 0
    signal = signals.json()["signals"][0]
    assert signal["decision_id"] == "llm-api-wait"
    assert signal["decision"] == "WAIT"
    assert signal["authority"] == "CHIEF_TRADER_LLM"
    assert signal["executable"] is False


async def test_api_killswitch_route(database):
    state = make_state(database)
    client = TestClient(create_app(state))
    assert client.get("/killswitch").json()["enabled"] is False
    response = client.post("/killswitch", json={"enabled": True, "reason": "api test"})
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert state.risk.kill_switch.enabled is True



async def test_api_read_only_trade_plan_episode_and_decision_detail_endpoints(database):
    state = make_state(database)
    client = TestClient(create_app(state))
    plans = client.get("/trade-plans")
    assert plans.status_code == 200
    body = plans.json()
    assert body["trade_plans"] == []
    assert body["count"] == 0

    episodes = client.get("/trade-episodes")
    assert episodes.status_code == 200
    body = episodes.json()
    assert body["trade_episodes"] == []
    assert body["count"] == 0

    missing = client.get("/llm/decisions/llm-does-not-exist")
    assert missing.status_code == 404

    await LLMDecisionStore(database.session_factory).save(
        ChiefTraderDecision(
            decision_id="llm-detail",
            symbol="BTCUSDT",
            action="NO_TRADE",
            market_regime="RANGE",
            thesis="detail endpoint",
            model_provider="deepseek",
            model="deepseek-v4-pro",
        ),
        run_id="run-api-detail",
        prompt_version="detail-v1",
        tool_refs=["funding", "orderbook"],
    )
    detail = TestClient(create_app(state)).get("/llm/decisions/llm-detail")
    assert detail.status_code == 200
    assert detail.json()["tool_refs"] == ["funding", "orderbook"]
    assert detail.json()["model_provider"] == "deepseek"
