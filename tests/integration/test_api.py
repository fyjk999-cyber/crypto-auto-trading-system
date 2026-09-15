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


def test_position_legs_endpoint_exposes_independence_contract(database):
    import asyncio

    from crypto_trader.execution.hedge_legs import (
        HedgeLegContract,
        LegKind,
        PositionLegService,
    )

    service = PositionLegService(database.session_factory)
    contract = HedgeLegContract(
        leg_id="leg-api-1",
        symbol="BTCUSDT",
        side="SHORT",
        kind=LegKind.HEDGE,
        strategy="MEAN_REVERT",
        thesis="independent mean-reversion short thesis",
        base_exit={"type": "PRICE", "trigger": "<=104", "size_pct": 100},
        invalidation="acceptance above 105",
        evidence_families=["model:mean_reversion"],
        reason="independent reversal thesis",
    )
    asyncio.run(
        service.register(
            contract,
            trade_plan_id="plan-hedge",
            decision_id="d-hedge",
            state_version="v1",
        )
    )

    response = TestClient(create_app(make_state(database))).get(
        "/position-legs", params={"symbol": "BTCUSDT"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["not_an_order"] is True
    leg = body["position_legs"][0]
    assert leg["leg_id"] == "leg-api-1"
    assert leg["kind"] == "HEDGE"
    assert leg["base_exit"]["trigger"] == "<=104"
    assert leg["evidence_families"] == ["model:mean_reversion"]


def test_growth_daily_report_endpoint_reads_frozen_top10_and_outcomes(database):
    import asyncio

    from crypto_trader.market_data.opportunity.daily_freeze import DailyOpportunityFreezer
    from crypto_trader.market_data.opportunity.outcomes import (
        OpportunityOutcomeRecorder,
        evaluate_opportunity,
    )

    freezer = DailyOpportunityFreezer(database.session_factory)
    recorder = OpportunityOutcomeRecorder(database.session_factory)
    asyncio.run(
        freezer.freeze(
            "2026-09-16",
            [{"symbol": "BTCUSDT", "score": 90.0, "candidate_source": "market_observer"}],
        )
    )
    asyncio.run(
        recorder.record(
            trading_day="2026-09-16",
            symbol="BTCUSDT",
            outcomes=evaluate_opportunity(
                frozen_price=100.0,
                expected_direction="LONG",
                traded=True,
                window_prices={"1h": 101.0},
            ),
        )
    )

    client = TestClient(create_app(make_state(database)))
    response = client.get("/growth/daily-report", params={"trading_day": "2026-09-16"})
    assert response.status_code == 200
    body = response.json()
    assert body["trading_day"] == "2026-09-16"
    assert body["top10"][0]["symbol"] == "BTCUSDT"
    assert body["outcomes"]["labels"]["TRADED_CORRECT"] == 1
    assert len(body["required_reviews"]) == 7
    assert body["authority"] == "LEARNING_ONLY"
    assert body["is_order"] is False
    assert body["can_modify_core"] is False

    empty = client.get("/growth/daily-report", params={"trading_day": "1999-01-01"})
    assert empty.status_code == 200
    assert empty.json()["top10"] == []


def test_lineage_coverage_endpoint_flags_untracked_fills(database):
    import asyncio
    from datetime import UTC, datetime
    from decimal import Decimal

    from crypto_trader.persistence.models import FillORM, OrderORM

    client = TestClient(create_app(make_state(database)))
    clean = client.get("/lineage/coverage")
    assert clean.status_code == 200
    assert clean.json()["ok"] is True
    assert clean.json()["untracked_count"] == 0

    now = datetime.now(UTC)

    async def seed():
        async with database.session_factory() as session:
            session.add(
                OrderORM(
                    internal_order_id="ord-api-lineage",
                    client_order_id="coid-api-lineage",
                    symbol="BTCUSDT",
                    side="BUY",
                    order_type="LIMIT",
                    time_in_force="GTC",
                    quantity=Decimal("0.1"),
                    status="FILLED",
                    trading_mode="PAPER",
                    strategy_id="live_llm",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                FillORM(
                    fill_id="fill-api-untracked",
                    order_id="ord-api-lineage",
                    client_order_id=None,
                    exchange_order_id=None,
                    symbol="BTCUSDT",
                    side="BUY",
                    price=Decimal("100"),
                    quantity=Decimal("0.1"),
                    timestamp=now,
                )
            )
            await session.commit()

    asyncio.run(seed())
    flagged = client.get("/lineage/coverage").json()
    assert flagged["ok"] is False
    assert flagged["flag"] == "UNTRACKED_FACTUAL_FILL"
    assert flagged["untracked"][0]["fill_id"] == "fill-api-untracked"
    assert flagged["is_order"] is False
