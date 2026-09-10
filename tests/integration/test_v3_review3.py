"""V3 review-3 focused regressions: funding provenance, lifecycles, fencing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.domain.enums import (
    LedgerDirection,
    LedgerEntryType,
    TradingMode,
)
from crypto_trader.domain.money import D
from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.governance.trade_episode import TradeEpisodeStore
from crypto_trader.ledger.service import FundingScope, LedgerPosting, LedgerService
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.order.manager import OrderManager
from crypto_trader.order.provenance import HistoricalQuantityStatus
from crypto_trader.perpetual.funding_coverage import FundingCoverageService
from crypto_trader.perpetual.funding_runtime import FundingAccountingSupervisor
from crypto_trader.perpetual.funding_settlement import (
    FundingSettlementService,
    canonical_utc_timestamp_text,
)
from crypto_trader.persistence.models import (
    FillORM,
    FundingEventResolutionORM,
    LedgerTransactionORM,
    OrderORM,
    TradeEpisodeORM,
)
from crypto_trader.trade_plan.service import TradePlanService, TradePlanState
from tests.conftest import make_paper_engine
from tests.integration.test_live_llm_position_lifecycle import (
    BTC_EXECUTION_METADATA,
    Evidence,
    MutableClock,
    SequencedChief,
)
from tests.integration.test_p8_daily_review_concurrency import (
    CLOSED_AT,
    REVIEW_DATE,
    _episode,
)

NOW = datetime(2026, 9, 10, 15, tzinfo=UTC)


@dataclass
class PlanSpec:
    trade_plan_id: str
    symbol: str
    opened_at: datetime
    closed_at: datetime | None
    state: str = "CLOSED"


class FakePlans:
    def __init__(self, plans: list[PlanSpec]):
        self.plans = plans

    async def lifecycles_overlapping(self, start, end):
        return [
            plan
            for plan in self.plans
            if plan.opened_at < end
            and (plan.closed_at is None or plan.closed_at >= start)
        ]

    async def get_active_for_symbol(self, symbol):
        return next(
            (
                plan
                for plan in self.plans
                if plan.symbol == symbol and plan.state == "ACTIVE"
            ),
            None,
        )

    async def latest_for_symbol(self, symbol):
        return next(
            (plan for plan in reversed(self.plans) if plan.symbol == symbol),
            None,
        )


class EmptyPortfolio:
    async def get_positions(self):
        return {}


class FakeCandleAdapter:
    expects_canonical_symbols = True

    def __init__(self, candles: dict[str, list[list[str]]]):
        self.candles = candles

    async def get_mark_price_candles(self, symbol, bar="1H", limit=100):
        return self.candles.get(symbol, [])


def _candle(hour: int, close: str) -> list[str]:
    return [
        str(int(datetime(2026, 9, 10, hour, tzinfo=UTC).timestamp() * 1000)),
        "1",
        "1",
        "1",
        close,
        "0",
        "0",
        "0",
        "1",
    ]


class RecordingIngestor:
    def __init__(
        self,
        coverage_service: FundingCoverageService,
        events_by_symbol: dict[str, list[tuple[datetime, str]]] | None = None,
    ):
        self.coverage_service = coverage_service
        self.events_by_symbol = events_by_symbol or {}

    async def ingest(self, adapter, **kwargs):
        instrument_id = kwargs["instrument_id"]
        window_start = kwargs["window_start"]
        window_end = kwargs["window_end"]
        events = [
            {
                "fundingTime": str(int(stamp.timestamp() * 1000)),
                "realizedRate": rate,
            }
            for stamp, rate in self.events_by_symbol.get(instrument_id, [])
            if window_start <= stamp < window_end
        ]
        return await self.coverage_service.record(
            instrument_id=instrument_id,
            window_start=window_start,
            window_end=window_end,
            coverage_status="KNOWN_VALUE" if events else "KNOWN_ZERO",
            pagination_complete=True,
            boundary_proof=True,
            events=events,
            fetched_count=len(events),
            window_event_count=len(events),
        )


async def _add_order_and_fill(
    database,
    *,
    order_id: str,
    fill_id: str,
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
    at: datetime,
) -> None:
    async with database.session_factory() as session:
        session.add(
            OrderORM(
                internal_order_id=order_id,
                client_order_id=f"client_{order_id}",
                symbol=symbol,
                side=side,
                order_type="MARKET",
                time_in_force="GTC",
                quantity=quantity,
                filled_quantity=quantity,
                status="FILLED",
                trading_mode=TradingMode.PAPER.value,
                strategy_id="v3",
                created_at=at,
                updated_at=at,
                metadata_json={"instrument_type": "LINEAR_PERP"},
            )
        )
        session.add(
            FillORM(
                fill_id=fill_id,
                order_id=order_id,
                symbol=symbol,
                side=side,
                price=price,
                quantity=quantity,
                fee=Decimal("0"),
                timestamp=at,
            )
        )
        await session.commit()


async def _add_verified_fill(
    database,
    ledger: LedgerService,
    *,
    fill_id: str,
    order_id: str,
    account_id: str,
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
    at: datetime,
) -> None:
    await _add_order_and_fill(
        database,
        order_id=order_id,
        fill_id=fill_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        at=at,
    )
    await ledger.record(
        LedgerEntryType.TRADE,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, D("1")),
            LedgerPosting("REALIZED_PNL", LedgerDirection.CREDIT, D("1")),
        ],
        account_id=account_id,
        instrument_id=symbol,
        fill_id=fill_id,
        transaction_id=f"txn_{fill_id}",
        created_at=at,
    )


async def test_historical_quantity_unproven_is_not_zero(database):
    manager = OrderManager(database.session_factory)
    missing = await manager.historical_quantity_at(
        account_id="default", symbol="BTC-USDT-SWAP", at=NOW
    )
    assert missing.status == HistoricalQuantityStatus.UNPROVEN
    assert missing.quantity is None

    await _add_order_and_fill(
        database,
        order_id="unproven_order",
        fill_id="unproven_fill",
        symbol="BTC-USDT-SWAP",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("100"),
        at=NOW - timedelta(hours=1),
    )
    unproven = await manager.historical_quantity_at(
        account_id="default", symbol="BTC-USDT-SWAP", at=NOW
    )
    assert unproven.status == HistoricalQuantityStatus.UNPROVEN
    assert unproven.quantity is None


async def test_historical_quantity_is_account_scoped(database):
    ledger = LedgerService(database.session_factory)
    manager = OrderManager(database.session_factory)
    await _add_verified_fill(
        database,
        ledger,
        fill_id="fill_a",
        order_id="order_a",
        account_id="account-a",
        symbol="BTC-USDT-SWAP",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("100"),
        at=NOW - timedelta(hours=3),
    )
    await _add_verified_fill(
        database,
        ledger,
        fill_id="fill_b",
        order_id="order_b",
        account_id="account-b",
        symbol="BTC-USDT-SWAP",
        side="SELL",
        quantity=Decimal("2"),
        price=Decimal("101"),
        at=NOW - timedelta(hours=2),
    )
    account_a = await manager.historical_quantity_at(
        account_id="account-a", symbol="BTC-USDT-SWAP", at=NOW
    )
    account_b = await manager.historical_quantity_at(
        account_id="account-b", symbol="BTC-USDT-SWAP", at=NOW
    )
    assert account_a.status == HistoricalQuantityStatus.PROVEN_VALUE
    assert account_a.quantity == Decimal("1")
    assert account_b.status == HistoricalQuantityStatus.PROVEN_VALUE
    assert account_b.quantity == Decimal("-2")

    await _add_verified_fill(
        database,
        ledger,
        fill_id="fill_a_close",
        order_id="order_a_close",
        account_id="account-a",
        symbol="BTC-USDT-SWAP",
        side="SELL",
        quantity=Decimal("1"),
        price=Decimal("102"),
        at=NOW - timedelta(hours=1),
    )
    flat = await manager.historical_quantity_at(
        account_id="account-a", symbol="BTC-USDT-SWAP", at=NOW
    )
    assert flat.status == HistoricalQuantityStatus.PROVEN_ZERO
    assert flat.quantity == Decimal("0")


def _closed_lifecycle_supervisor(
    database,
    plans: list[PlanSpec],
    candles: dict[str, list[list[str]]],
    events: dict[str, list[tuple[datetime, str]]],
):
    coverage_service = FundingCoverageService(database.session_factory)
    ledger = LedgerService(database.session_factory)
    ingestor = RecordingIngestor(coverage_service, events)
    supervisor = FundingAccountingSupervisor(
        adapter=FakeCandleAdapter(candles),
        ingestor=ingestor,
        settlement_service=FundingSettlementService(ledger),
        portfolio=EmptyPortfolio(),
        trade_plans=FakePlans(plans),
        ledger=ledger,
        order_manager=OrderManager(database.session_factory),
        trade_episodes=TradeEpisodeStore(database.session_factory),
        instruments_provider=lambda: {
            "BTC-USDT-SWAP": {
                "symbol": "BTC-USDT-SWAP",
                "instrument_type": "LINEAR_PERP",
                "contract_size": Decimal("0.01"),
                "contract_multiplier": Decimal("1"),
            }
        },
        lookback_hours=240,
    )
    return supervisor, coverage_service, ledger


async def test_closed_lifecycle_known_value_is_settled(database):
    await _add_verified_fill(
        database,
        LedgerService(database.session_factory),
        fill_id="closed_fill",
        order_id="closed_order",
        account_id="default",
        symbol="BTC-USDT-SWAP",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("100"),
        at=datetime(2026, 9, 10, 7, 50, tzinfo=UTC),
    )
    plan = PlanSpec(
        trade_plan_id="plan-closed",
        symbol="BTC-USDT-SWAP",
        opened_at=datetime(2026, 9, 10, 8, tzinfo=UTC),
        closed_at=datetime(2026, 9, 10, 12, 5, tzinfo=UTC),
    )
    supervisor, _, ledger = _closed_lifecycle_supervisor(
        database,
        [plan],
        {"BTC-USDT-SWAP": [_candle(11, "100")]},
        {
            "BTC-USDT-SWAP": [
                (datetime(2026, 9, 10, 12, tzinfo=UTC), "0.001")
            ]
        },
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 1

    async with database.session_factory() as session:
        resolutions = (
            await session.execute(select(FundingEventResolutionORM))
        ).scalars().all()
        transactions = (
            await session.execute(
                select(LedgerTransactionORM).where(
                    LedgerTransactionORM.entry_type.in_(
                        ("FUNDING_RECEIPT", "FUNDING_PAYMENT")
                    )
                )
            )
        ).scalars().all()
    assert len(resolutions) == 1
    assert resolutions[0].status == "SETTLED"
    assert resolutions[0].settlement_timestamp.replace(
        tzinfo=None
    ) == datetime(2026, 9, 10, 12)
    event_id = "default|BTC-USDT-SWAP|" + canonical_utc_timestamp_text(
        datetime(2026, 9, 10, 12, tzinfo=UTC)
    )
    assert await ledger.transaction_id_for_event(event_id) is not None
    assert len(transactions) == 1


async def test_multiple_same_symbol_lifecycles_are_all_covered(database):
    await _add_verified_fill(
        database,
        LedgerService(database.session_factory),
        fill_id="multi_fill",
        order_id="multi_order",
        account_id="default",
        symbol="BTC-USDT-SWAP",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("100"),
        at=datetime(2026, 9, 10, 0, 50, tzinfo=UTC),
    )
    plans = [
        PlanSpec(
            trade_plan_id="plan-a",
            symbol="BTC-USDT-SWAP",
            opened_at=datetime(2026, 9, 10, 1, tzinfo=UTC),
            closed_at=datetime(2026, 9, 10, 5, tzinfo=UTC),
        ),
        PlanSpec(
            trade_plan_id="plan-b",
            symbol="BTC-USDT-SWAP",
            opened_at=datetime(2026, 9, 10, 10, tzinfo=UTC),
            closed_at=datetime(2026, 9, 10, 11, tzinfo=UTC),
        ),
        PlanSpec(
            trade_plan_id="plan-c",
            symbol="BTC-USDT-SWAP",
            opened_at=datetime(2026, 9, 10, 12, tzinfo=UTC),
            closed_at=datetime(2026, 9, 10, 13, tzinfo=UTC),
        ),
    ]
    supervisor, coverage_service, ledger = _closed_lifecycle_supervisor(
        database,
        plans,
        {"BTC-USDT-SWAP": [_candle(3, "100")]},
        {
            "BTC-USDT-SWAP": [
                (datetime(2026, 9, 10, 4, tzinfo=UTC), "0.001")
            ]
        },
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 1

    scopes = []
    coverage_by_scope = {}
    for plan in plans:
        end = plan.closed_at + timedelta(microseconds=1)
        scope = FundingScope(
            account_id="default",
            currency="USDT",
            instrument_id=plan.symbol,
            window_start=plan.opened_at,
            window_end=end,
            lifecycle_id=plan.trade_plan_id,
        )
        scopes.append(scope)
        coverage = await coverage_service.coverage_for(
            instrument_id=plan.symbol, start=plan.opened_at, end=end
        )
        assert coverage is not None
        coverage_by_scope[plan.trade_plan_id] = (
            coverage.coverage_status,
            coverage.window_events,
        )

    start = datetime(2026, 9, 10, tzinfo=UTC)
    end = datetime(2026, 9, 11, tzinfo=UTC)
    provenance = await ledger.net_pnl_provenance_since(
        start,
        account_id="default",
        currency="USDT",
        instrument_ids=[],
        end=end,
        funding_scopes=scopes,
        coverage_by_scope=coverage_by_scope,
    )
    assert provenance.complete is True
    assert len(provenance.scope_provenances) == 3
    assert provenance.funding_amount is not None
    assert provenance.funding_amount != 0
    assert {scope.coverage_status for scope in provenance.scope_provenances} == {
        "KNOWN_VALUE",
        "KNOWN_ZERO",
    }

    incomplete = await ledger.net_pnl_provenance_since(
        start,
        account_id="default",
        currency="USDT",
        instrument_ids=[],
        end=end,
        funding_scopes=scopes,
        coverage_by_scope={
            **coverage_by_scope,
            "plan-a": ("UNKNOWN", None),
        },
    )
    assert incomplete.complete is False
    assert incomplete.funding_status == "ACCOUNTING_INCOMPLETE"
    assert any(
        "FUNDING_COVERAGE_UNKNOWN" in reason
        for reason in incomplete.unknown_reasons
    )


async def _close_engine_lifecycle(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    clock = MutableClock()
    engine.clock = clock
    await engine.start("run-v3-lifecycle")
    assert await engine._strategy_context("BTCUSDT") is not None
    decisions = LLMDecisionStore(database.session_factory)
    plans = TradePlanService(database.session_factory)
    entry = ChiefTraderDecision(
        decision_id="entry-v3",
        symbol="BTCUSDT",
        action="LONG",
        market_regime="TREND",
        thesis="v3 factual lifecycle",
        position_size_request=0.1,
        leverage_request=5,
        stop_loss=95,
        model_provider="deepseek",
        model="deepseek-v4-pro",
    )
    await decisions.save(entry, run_id=engine.run_id, prompt_version="v3")
    plan, signal = await LiveLLMTradePlanner(plans).create_entry_signal(
        entry, limit_price=Decimal("101"),
        execution_metadata=BTC_EXECUTION_METADATA,
    )
    assert plan is not None and signal is not None
    await decisions.link_trade_plan(entry.decision_id, plan.trade_plan_id)
    await engine.process_signal(signal)
    await engine.wait_for_event_queue()
    engine.position_manager = LiveLLMPositionManager(
        chief=SequencedChief([("EXIT", "0")]),
        evidence_engine=Evidence(),
        decisions=decisions,
        plans=plans,
        audit=engine.audit,
        review_cooldown_seconds=30,
    )
    clock.advance()
    await engine.tick()
    await engine.wait_for_event_queue()
    closed_plan = await plans.get(plan.trade_plan_id)
    assert closed_plan is not None and closed_plan.state == TradePlanState.CLOSED
    return engine, closed_plan


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def test_incomplete_funding_blocks_factual_episode(database):
    engine, closed_plan = await _close_engine_lifecycle(database)
    async with database.session_factory() as session:
        assert (await session.execute(select(TradeEpisodeORM))).scalars().all() == []

    opened_at = _as_utc(closed_plan.opened_at)
    closed_at = _as_utc(closed_plan.closed_at)
    coverage_service = FundingCoverageService(database.session_factory)
    window_start = opened_at - timedelta(seconds=1)
    window_end = closed_at + timedelta(seconds=1)
    await coverage_service.record(
        instrument_id="BTCUSDT",
        window_start=window_start,
        window_end=window_end,
        coverage_status="UNKNOWN",
        pagination_complete=True,
        boundary_proof=True,
        events=[],
    )
    assert await engine.trade_episodes.materialize_pending_closed() == 0
    await coverage_service.record(
        instrument_id="BTCUSDT",
        window_start=window_start,
        window_end=window_end,
        coverage_status="KNOWN_ZERO",
        pagination_complete=True,
        boundary_proof=True,
        events=[],
    )
    created = await engine.trade_episodes.materialize_pending_closed()
    assert created == 1
    async with database.session_factory() as session:
        episodes = (await session.execute(select(TradeEpisodeORM))).scalars().all()
    assert len(episodes) == 1
    assert episodes[0].funding_pnl == Decimal("0")
    assert episodes[0].factual is True
    assert await engine.trade_episodes.materialize_pending_closed() == 0


async def test_episode_materializes_after_funding_recovery(database):
    engine, closed_plan = await _close_engine_lifecycle(database)
    opened_at = _as_utc(closed_plan.opened_at)
    closed_at = _as_utc(closed_plan.closed_at)
    hold = closed_at - opened_at
    event_at = opened_at + hold / 2
    event_at = event_at.replace(
        microsecond=(event_at.microsecond // 1000) * 1000
    )
    if not opened_at < event_at < closed_at:
        event_at = opened_at + timedelta(milliseconds=1)
    assert opened_at < event_at < closed_at
    coverage_service = FundingCoverageService(database.session_factory)
    await coverage_service.record(
        instrument_id="BTCUSDT",
        window_start=opened_at - timedelta(seconds=1),
        window_end=closed_at + timedelta(seconds=1),
        coverage_status="KNOWN_VALUE",
        pagination_complete=True,
        boundary_proof=True,
        events=[
            {
                "fundingTime": str(int(event_at.timestamp() * 1000)),
                "realizedRate": "0.001",
            }
        ],
        fetched_count=1,
        window_event_count=1,
    )
    await coverage_service.record_event_resolution(
        account_id="default",
        instrument_id="BTCUSDT",
        settlement_timestamp=event_at,
        status="MARK_UNAVAILABLE",
        quantity=Decimal("0.1"),
        funding_rate=Decimal("0.001"),
        reason="NO_CLOSED_CANDLE",
    )
    assert await engine.trade_episodes.materialize_pending_closed() == 0

    amount = await FundingSettlementService(engine.ledger).settle(
        account_id="default",
        instrument_id="BTCUSDT",
        settlement_timestamp=event_at,
        signed_quantity=Decimal("0.1"),
        mark_price=Decimal("101"),
        funding_rate=Decimal("0.001"),
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
    )
    transaction_id = await engine.ledger.transaction_id_for_event(
        "default|BTCUSDT|" + canonical_utc_timestamp_text(event_at)
    )
    await coverage_service.record_event_resolution(
        account_id="default",
        instrument_id="BTCUSDT",
        settlement_timestamp=event_at,
        status="SETTLED",
        quantity=Decimal("0.1"),
        mark_price=Decimal("101"),
        funding_rate=Decimal("0.001"),
        ledger_transaction_id=transaction_id,
    )
    assert await engine.trade_episodes.materialize_pending_closed() == 1
    async with database.session_factory() as session:
        episode = (await session.execute(select(TradeEpisodeORM))).scalar_one()
    assert episode.funding_pnl == amount


async def test_stale_review_token_cannot_mark_reviewed(database):
    async with database.session_factory() as session:
        session.add(_episode(1))
        await session.commit()
    persistence = MemoryPersistence(database.session_factory)
    window_start = datetime(2026, 9, 9, tzinfo=UTC)
    window_end = window_start + timedelta(days=1)
    token_a = await persistence.begin_daily_review(
        REVIEW_DATE,
        window_start,
        window_end,
        owner="worker-a",
        lease_seconds=3600,
    )
    assert token_a is not None
    blocked_revision = await persistence.begin_daily_review(
        REVIEW_DATE,
        window_start,
        window_end,
        owner="worker-b",
        lease_seconds=3600,
        allow_revision=True,
    )
    assert blocked_revision is None

    async with database.session_factory() as session:
        row = (
            await session.execute(
                select(FundingEventResolutionORM).where(
                    FundingEventResolutionORM.account_id == "never"
                )
            )
        ).scalar_one_or_none()
        assert row is None
    from crypto_trader.persistence.models import DailyReviewRunORM

    async with database.session_factory() as session:
        review = (
            await session.execute(
                select(DailyReviewRunORM).where(
                    DailyReviewRunORM.review_date == REVIEW_DATE
                )
            )
        ).scalar_one()
        review.claim_deadline_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    token_b = await persistence.begin_daily_review(
        REVIEW_DATE,
        window_start,
        window_end,
        owner="worker-b",
        lease_seconds=3600,
        allow_revision=True,
    )
    assert token_b is not None and token_b != token_a

    store = TradeEpisodeStore(database.session_factory)
    assert (
        await store.mark_reviewed_fenced(
            ["p8_ep_1"],
            review_date=REVIEW_DATE,
            claim_token=token_a,
            owner="worker-a",
        )
        is False
    )
    async with database.session_factory() as session:
        episode = (await session.execute(select(TradeEpisodeORM))).scalar_one()
        assert episode.review_status == "PENDING"
    assert (
        await store.mark_reviewed_fenced(
            ["p8_ep_1"],
            review_date=REVIEW_DATE,
            claim_token=token_b,
            owner="worker-b",
        )
        is True
    )
    async with database.session_factory() as session:
        episode = (await session.execute(select(TradeEpisodeORM))).scalar_one()
        assert episode.review_status == "REVIEWED"
    assert CLOSED_AT is not None


async def test_episode_owner_is_never_inferred_from_unrelated_funding(database):
    engine, closed_plan = await _close_engine_lifecycle(database)
    opened_at = _as_utc(closed_plan.opened_at)
    closed_at = _as_utc(closed_plan.closed_at)

    async with database.session_factory() as session:
        entry_fills = (
            await session.execute(
                select(FillORM).where(FillORM.order_id == closed_plan.order_id)
            )
        ).scalars().all()
    assert entry_fills
    entry_fill_id = entry_fills[0].fill_id
    async with database.session_factory() as session:
        transactions = (
            await session.execute(
                select(LedgerTransactionORM).where(
                    LedgerTransactionORM.fill_id == entry_fill_id
                )
            )
        ).scalars().all()
    assert transactions
    async with database.session_factory() as session:
        persisted = (
            await session.execute(
                select(LedgerTransactionORM).where(
                    LedgerTransactionORM.fill_id == entry_fill_id
                )
            )
        ).scalars().all()
        for transaction in persisted:
            transaction.ownership_status = "UNKNOWN"
            transaction.account_id = None
        await session.commit()
    async with database.session_factory() as session:
        left = (
            await session.execute(
                select(LedgerTransactionORM).where(
                    LedgerTransactionORM.fill_id == entry_fill_id,
                    LedgerTransactionORM.ownership_status == "VERIFIED",
                )
            )
        ).scalars().all()
    assert left == []

    ledger = LedgerService(database.session_factory)
    await ledger.record(
        LedgerEntryType.FUNDING_RECEIPT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, D("1")),
            LedgerPosting("FUNDING_RECEIPT", LedgerDirection.CREDIT, D("1")),
        ],
        account_id="unrelated-owner",
        instrument_id="BTCUSDT",
        transaction_id="unrelated_funding",
        created_at=opened_at + timedelta(seconds=2),
    )
    coverage_service = FundingCoverageService(database.session_factory)
    await coverage_service.record(
        instrument_id="BTCUSDT",
        window_start=opened_at - timedelta(seconds=1),
        window_end=closed_at + timedelta(seconds=1),
        coverage_status="KNOWN_ZERO",
        pagination_complete=True,
        boundary_proof=True,
        events=[],
    )
    assert await engine.trade_episodes.materialize_pending_closed() == 0
    async with database.session_factory() as session:
        assert (await session.execute(select(TradeEpisodeORM))).scalars().all() == []
