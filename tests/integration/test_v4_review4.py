"""V4 focused regressions: venue boundary, mark candles, spec, recovery, fence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.ledger.service import FundingScope, LedgerService
from crypto_trader.order.manager import OrderManager
from crypto_trader.order.provenance import HistoricalQuantityStatus
from crypto_trader.perpetual.funding_boundary import (
    FundingPublicDataBoundary,
    FundingSymbolMappingError,
)
from crypto_trader.perpetual.funding_coverage import FundingCoverageService
from crypto_trader.perpetual.funding_runtime import FundingAccountingSupervisor
from crypto_trader.perpetual.funding_settlement import FundingSettlementService
from crypto_trader.persistence.models import (
    DailyReviewRunORM,
    FundingEventResolutionORM,
    LedgerEntryORM,
    LedgerTransactionORM,
    TradeEpisodeORM,
)
from tests.integration.test_p8_daily_review_concurrency import REVIEW_DATE, _episode

NOW = datetime(2026, 9, 12, 15, tzinfo=UTC)


class RecordingOkxClient:
    def __init__(self, mark_rows=None):
        self.calls = []
        self.mark_rows = mark_rows or []

    async def get_funding_rate_history(self, symbol, *, before=None, after=None, limit=100):
        self.calls.append(("funding", symbol, before, after))
        return []

    async def get_mark_price_candles(self, symbol, *, bar="1H", limit=100):
        self.calls.append(("mark", symbol, bar))
        return self.mark_rows


@dataclass
class Plan:
    trade_plan_id: str
    symbol: str
    opened_at: datetime
    closed_at: datetime | None
    order_id: str | None = None
    state: str = "CLOSED"


class FakePlans:
    def __init__(self, plans):
        self.plans = plans

    async def lifecycles_overlapping(self, start, end):
        return [
            plan
            for plan in self.plans
            if plan.opened_at < end
            and (plan.closed_at is None or plan.closed_at >= start)
        ]

    async def get(self, trade_plan_id):
        return next(
            (plan for plan in self.plans if plan.trade_plan_id == trade_plan_id),
            None,
        )

    async def plan_covering(self, symbol, instant):
        rows = [
            plan
            for plan in self.plans
            if plan.symbol == symbol
            and plan.opened_at < instant
            and (plan.closed_at is None or plan.closed_at >= instant)
        ]
        return rows[0] if len(rows) == 1 else None


class EmptyPortfolio:
    async def get_positions(self):
        return {}


class MarkOnlyAdapter:
    def __init__(
        self,
        rows,
        funding_rows=None,
        *,
        expects_canonical_symbols=True,
        ordinary_rows=None,
    ):
        self.rows = rows
        self.funding_rows = funding_rows or []
        self.ordinary_calls = []
        self.ordinary_rows = ordinary_rows or []
        self.expects_canonical_symbols = expects_canonical_symbols

    async def get_funding_rate_history(self, symbol, *, before=None, after=None, limit=100):
        return list(self.funding_rows)

    async def get_mark_price_candles(self, symbol, *, bar="1H", limit=100):
        return list(self.rows)

    async def get_candles(self, *args, **kwargs):
        self.ordinary_calls.append(args)
        return list(self.ordinary_rows)


class RecordingIngestor:
    def __init__(self, coverage_service, events_by_symbol):
        self.coverage_service = coverage_service
        self.events_by_symbol = events_by_symbol

    async def ingest(self, adapter, **kwargs):
        symbol = kwargs["instrument_id"]
        start = kwargs["window_start"]
        end = kwargs["window_end"]
        events = [
            {
                "fundingTime": str(int(stamp.timestamp() * 1000)),
                "realizedRate": rate,
            }
            for stamp, rate in self.events_by_symbol.get(symbol, [])
            if start <= stamp < end
        ]
        return await self.coverage_service.record(
            instrument_id=symbol,
            window_start=start,
            window_end=end,
            coverage_status="KNOWN_VALUE" if events else "KNOWN_ZERO",
            pagination_complete=True,
            boundary_proof=True,
            events=events,
            fetched_count=len(events),
            window_event_count=len(events),
        )


class FakeOrderManager:
    def __init__(self, order=None):
        self.order = order

    async def historical_quantity_at(self, *, account_id, symbol, at, currency="USDT"):
        return __import__(
            "crypto_trader.order.provenance", fromlist=["HistoricalQuantityProvenance"]
        ).HistoricalQuantityProvenance(
            account_id=account_id,
            instrument_id=symbol,
            settlement_timestamp=at,
            status=HistoricalQuantityStatus.PROVEN_VALUE,
            quantity=Decimal("1"),
            source="FAKE",
        )

    async def get(self, order_id):
        return self.order


def _spec(symbol="BTC-USDT-SWAP") -> dict:
    return {
        symbol: {
            "symbol": symbol,
            "instrument_type": "LINEAR_PERP",
            "contract_size": Decimal("0.01"),
            "contract_multiplier": Decimal("1"),
        }
    }


def _event(stamp: datetime, rate: str = "0.001") -> dict:
    return {
        "fundingTime": str(int(stamp.timestamp() * 1000)),
        "realizedRate": rate,
    }


async def _supervisor(
    database,
    *,
    plans,
    events_by_symbol,
    mark_rows,
    instruments=None,
    order_manager=None,
    funding_rows=None,
    trade_episodes=None,
    lookback_hours=240,
    expects_canonical_symbols=True,
    ordinary_rows=None,
):
    coverage_service = FundingCoverageService(database.session_factory)
    ledger = LedgerService(database.session_factory)
    ingestor = RecordingIngestor(coverage_service, events_by_symbol)
    adapter = MarkOnlyAdapter(
        mark_rows,
        funding_rows or [],
        expects_canonical_symbols=expects_canonical_symbols,
        ordinary_rows=ordinary_rows,
    )
    supervisor = FundingAccountingSupervisor(
        adapter=adapter,
        ingestor=ingestor,
        settlement_service=FundingSettlementService(ledger),
        portfolio=EmptyPortfolio(),
        trade_plans=FakePlans(plans),
        ledger=ledger,
        order_manager=order_manager or FakeOrderManager(),
        trade_episodes=trade_episodes,
        instruments_provider=lambda: (
            instruments if instruments is not None else _spec()
        ),
        lookback_hours=lookback_hours,
    )
    return supervisor, coverage_service, ledger, adapter


async def test_okx_boundary_maps_canonical_dynamic_symbols():
    client = RecordingOkxClient()
    boundary = FundingPublicDataBoundary(client)
    await boundary.get_funding_rate_history("BTCUSDT")
    await boundary.get_funding_rate_history("SOLUSDT")
    assert client.calls[0][1] == "BTC-USDT-SWAP"
    assert client.calls[1][1] == "SOL-USDT-SWAP"
    with pytest.raises(FundingSymbolMappingError):
        boundary.venue_symbol("UNMAPPABLE")

    # Internal identities stay canonical; only the venue call is mapped.
    scope = FundingScope(
        account_id="default",
        currency="USDT",
        instrument_id="BTCUSDT",
        window_start=NOW - timedelta(hours=1),
        window_end=NOW,
    )
    assert scope.instrument_id == "BTCUSDT"


async def test_supervisor_symbol_mapping_failure_is_explicit(database):
    plan = Plan(
        trade_plan_id="bad-plan",
        symbol="UNMAPPABLE",
        opened_at=NOW - timedelta(hours=3),
        closed_at=NOW - timedelta(hours=2),
    )
    supervisor, _, _, _ = await _supervisor(
        database,
        plans=[plan],
        events_by_symbol={},
        mark_rows=[],
        lookback_hours=24,
        expects_canonical_symbols=False,
    )
    report = await supervisor.run_once(now=NOW)
    assert any("SYMBOL_MAPPING_FAILED" in item for item in report.errors)
    assert report.settled == 0


async def test_mark_price_candle_wins_over_ordinary_candle(database):
    opened = NOW - timedelta(hours=3)
    event = NOW - timedelta(hours=2)
    plan = Plan("plan-mark", "BTC-USDT-SWAP", opened, NOW)
    mark_rows = [
        _candle_row(event - timedelta(hours=1), "200"),
    ]
    events = {"BTC-USDT-SWAP": [(event, "0.001")]}
    supervisor, coverage_service, ledger, adapter = await _supervisor(
        database,
        plans=[plan],
        events_by_symbol=events,
        mark_rows=mark_rows,
        ordinary_rows=[_candle_row(event - timedelta(hours=1), "300")],
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 1
    assert adapter.ordinary_calls == []
    async with database.session_factory() as session:
        rows = (
            await session.execute(
                select(LedgerTransactionORM).where(
                    LedgerTransactionORM.entry_type == "FUNDING_PAYMENT"
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    entry = (
        await session.execute(
            select(LedgerEntryORM).where(
                LedgerEntryORM.transaction_id == rows[0].transaction_id,
                LedgerEntryORM.account == "FUNDING_PAYMENT",
            )
        )
    ).scalar_one()
    # quantity 1 * mark 200 * size 0.01 * multiplier 1 * rate 0.001
    assert entry.amount == Decimal("0.002")


def _candle_row(open_at: datetime, close: str, confirm: str = "1") -> list[str]:
    return [
        str(int(open_at.timestamp() * 1000)),
        "1",
        "1",
        "1",
        close,
        "0",
        "0",
        "0",
        confirm,
    ]


@pytest.mark.parametrize(
    "rows",
    [
        [_candle_row(NOW - timedelta(hours=1), "100", confirm="0")],
        [_candle_row(NOW - timedelta(hours=1), "100")],  # closes after event
        [_candle_row(NOW - timedelta(hours=5), "100")],  # stale
    ],
)
async def test_mark_price_unavailable_variants(database, rows):
    event = NOW - timedelta(hours=2)
    plan = Plan("plan-mark", "BTC-USDT-SWAP", NOW - timedelta(hours=3), NOW)
    events = {"BTC-USDT-SWAP": [(event, "0.001")]}
    supervisor, coverage_service, ledger, adapter = await _supervisor(
        database,
        plans=[plan],
        events_by_symbol=events,
        mark_rows=rows,
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 0
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
    assert resolutions[0].status == "MARK_UNAVAILABLE"
    assert transactions == []


async def test_contract_spec_missing_blocks_settlement(database):
    event = NOW - timedelta(hours=2)
    plan = Plan(
        "plan-spec",
        "BTC-USDT-SWAP",
        NOW - timedelta(hours=3),
        NOW,
        order_id="spec_order",
    )
    order = type(
        "Order",
        (),
        {
            "internal_order_id": "spec_order",
            "symbol": "BTC-USDT-SWAP",
            "metadata_json": {"instrument_type": "LINEAR_PERP"},
        },
    )()
    events = {"BTC-USDT-SWAP": [(event, "0.001")]}
    supervisor, coverage_service, ledger, _ = await _supervisor(
        database,
        plans=[plan],
        events_by_symbol=events,
        mark_rows=[_candle_row(event - timedelta(hours=1), "100")],
        instruments={},
        order_manager=FakeOrderManager(order=order),
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 0
    assert any("INSTRUMENT_CONTRACT_SPEC_UNPROVEN" in item for item in report.skipped)
    async with database.session_factory() as session:
        resolutions = (
            await session.execute(select(FundingEventResolutionORM))
        ).scalars().all()
    assert resolutions[0].status == "UNPROVEN"
    assert "INSTRUMENT_CONTRACT_SPEC_UNPROVEN" in resolutions[0].reason


async def test_durable_order_spec_allows_recovery_settlement(database):
    event = NOW - timedelta(hours=2)
    plan = Plan(
        "plan-spec-ok",
        "BTC-USDT-SWAP",
        NOW - timedelta(hours=3),
        NOW,
        order_id="spec_order_ok",
    )
    order = type(
        "Order",
        (),
        {
            "internal_order_id": "spec_order_ok",
            "symbol": "BTC-USDT-SWAP",
            "metadata_json": {
                "instrument_type": "LINEAR_PERP",
                "contract_size": "0.01",
                "contract_multiplier": "1",
            },
        },
    )()
    events = {"BTC-USDT-SWAP": [(event, "0.001")]}
    supervisor, _, _, _ = await _supervisor(
        database,
        plans=[plan],
        events_by_symbol=events,
        mark_rows=[_candle_row(event - timedelta(hours=1), "100")],
        instruments={},
        order_manager=FakeOrderManager(order=order),
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 1


async def test_48h_old_mark_unavailable_is_recovered(database):
    opened = NOW - timedelta(hours=50)
    closed = NOW - timedelta(hours=46)
    event = NOW - timedelta(hours=48)
    plan = Plan("plan-48h", "BTC-USDT-SWAP", opened, closed)
    supervisor, coverage_service, ledger, _ = await _supervisor(
        database,
        plans=[plan],
        events_by_symbol={},
        mark_rows=[_candle_row(event - timedelta(hours=1), "100")],
        lookback_hours=24,
    )
    await coverage_service.record_event_resolution(
        account_id="default",
        instrument_id="BTC-USDT-SWAP",
        settlement_timestamp=event,
        status="MARK_UNAVAILABLE",
        quantity=Decimal("1"),
        funding_rate=Decimal("0.001"),
        trade_plan_id="plan-48h",
        reason="NO_CLOSED_MARK_PRICE_CANDLE",
    )
    first = await supervisor.run_once(now=NOW)
    assert first.settled == 1
    second = await supervisor.run_once(now=NOW)
    assert second.settled == 0
    async with database.session_factory() as session:
        transactions = (
            await session.execute(
                select(LedgerTransactionORM).where(
                    LedgerTransactionORM.entry_type.in_(
                        ("FUNDING_RECEIPT", "FUNDING_PAYMENT")
                    )
                )
            )
        ).scalars().all()
    assert len(transactions) == 1


async def test_unresolved_ownership_and_contract_spec_stay_unresolved(database):
    event = NOW - timedelta(hours=48)
    opened = NOW - timedelta(hours=50)
    closed = NOW - timedelta(hours=46)
    plan = Plan("plan-unresolved", "BTC-USDT-SWAP", opened, closed)
    supervisor, coverage_service, _, _ = await _supervisor(
        database,
        plans=[plan],
        events_by_symbol={},
        mark_rows=[_candle_row(event - timedelta(hours=1), "100")],
        instruments={},
        order_manager=OrderManager(database.session_factory),
        lookback_hours=24,
    )
    # No verified fills and no durable contract spec.
    await coverage_service.record_event_resolution(
        account_id="default",
        instrument_id="BTC-USDT-SWAP",
        settlement_timestamp=event,
        status="MARK_UNAVAILABLE",
        quantity=None,
        funding_rate=Decimal("0.001"),
        trade_plan_id="plan-unresolved",
        reason="NO_CLOSED_MARK_PRICE_CANDLE",
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 0
    async with database.session_factory() as session:
        resolution = (
            await session.execute(select(FundingEventResolutionORM))
        ).scalar_one()
    assert resolution.status == "UNPROVEN"


class RecoveryAwareEpisodes:
    def __init__(self, coverage_service):
        self.coverage_service = coverage_service
        self.calls = []

    async def materialize_pending_closed(self):
        unresolved = await self.coverage_service.retryable_unresolved()
        self.calls.append("incomplete" if unresolved else "complete")
        return 0


async def test_episode_materialization_waits_for_recovery_complete(database):
    event = NOW - timedelta(hours=48)
    opened = NOW - timedelta(hours=50)
    closed = NOW - timedelta(hours=46)
    plan = Plan("plan-materialize", "BTC-USDT-SWAP", opened, closed)
    coverage_service = FundingCoverageService(database.session_factory)
    episodes = RecoveryAwareEpisodes(coverage_service)
    supervisor, _, _, _ = await _supervisor(
        database,
        plans=[plan],
        events_by_symbol={},
        mark_rows=[_candle_row(event - timedelta(hours=1), "100")],
        trade_episodes=episodes,
        lookback_hours=24,
    )
    await coverage_service.record_event_resolution(
        account_id="default",
        instrument_id="BTC-USDT-SWAP",
        settlement_timestamp=event,
        status="MARK_UNAVAILABLE",
        quantity=Decimal("1"),
        funding_rate=Decimal("0.001"),
        trade_plan_id="plan-materialize",
        reason="NO_CLOSED_MARK_PRICE_CANDLE",
    )
    await supervisor.run_once(now=NOW)
    assert episodes.calls == ["complete"]


async def test_review_mark_cas_blocks_takeover_through_transaction(database):
    async with database.session_factory() as session:
        session.add(_episode(1))
        await session.commit()
    persistence = MemoryPersistence(database.session_factory)
    window_start = datetime(2026, 9, 9, tzinfo=UTC)
    window_end = window_start + timedelta(days=1)
    token_a = await persistence.begin_daily_review(
        REVIEW_DATE, window_start, window_end, owner="worker-a", lease_seconds=3600
    )
    assert token_a is not None

    async with database.session_factory() as session:
        now = datetime.now(UTC)
        result = await session.execute(
            update(DailyReviewRunORM)
            .where(
                DailyReviewRunORM.review_date == REVIEW_DATE,
                DailyReviewRunORM.claim_token == token_a,
                DailyReviewRunORM.owner == "worker-a",
                DailyReviewRunORM.status.in_(("RUNNING", "SUCCEEDED")),
                DailyReviewRunORM.claim_deadline_at.is_not(None),
                DailyReviewRunORM.claim_deadline_at >= now,
            )
            .values(claim_deadline_at=now + timedelta(minutes=5))
        )
        assert result.rowcount == 1

        b_result = {}

        async def attempt_takeover():
            try:
                token = await persistence.begin_daily_review(
                    REVIEW_DATE,
                    window_start,
                    window_end,
                    owner="worker-b",
                    lease_seconds=3600,
                    allow_revision=True,
                )
                b_result["token"] = token
            except Exception as exc:
                b_result["error"] = type(exc).__name__

        task = asyncio.create_task(attempt_takeover())
        try:
            await asyncio.wait_for(task, timeout=2)
        except TimeoutError:
            b_result["timeout"] = True
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # While A holds the uncommitted fence transaction, B must not own.
        assert b_result.get("token") is None

        # Simulate A finishing episode mutation in the same transaction.
        episode = (
            await session.execute(select(TradeEpisodeORM))
        ).scalar_one()
        episode.review_status = "REVIEWED"
        await session.commit()

    # After A commits and the old lease expires/abandons, B takes over.
    async with database.session_factory() as session:
        review = (
            await session.execute(
                select(DailyReviewRunORM).where(
                    DailyReviewRunORM.review_date == REVIEW_DATE
                )
            )
        ).scalar_one()
        review.status = "SUCCEEDED"
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


async def test_episode_owner_wrong_instrument_blocks_episode(database):
    # The V3 owner-inference regression remains the broad guard; this test
    # exercises the exact wrong-instrument ledger lineage case.
    from tests.integration.test_v3_review3 import _close_engine_lifecycle

    engine, closed_plan = await _close_engine_lifecycle(database)
    coverage_service = FundingCoverageService(database.session_factory)
    opened = closed_plan.opened_at
    closed = closed_plan.closed_at
    await coverage_service.record(
        instrument_id="BTCUSDT",
        window_start=opened - timedelta(seconds=1),
        window_end=closed + timedelta(seconds=1),
        coverage_status="KNOWN_ZERO",
        pagination_complete=True,
        boundary_proof=True,
        events=[],
    )
    async with database.session_factory() as session:
        rows = (
            await session.execute(
                select(LedgerTransactionORM).where(
                    LedgerTransactionORM.fill_id.is_not(None),
                    LedgerTransactionORM.account_id == "default",
                    LedgerTransactionORM.ownership_status == "VERIFIED",
                )
            )
        ).scalars().all()
        for row in rows:
            row.instrument_id = "WRONG-USDT-SWAP"
        await session.commit()
    assert await engine.trade_episodes.materialize_pending_closed() == 0
    async with database.session_factory() as session:
        assert (await session.execute(select(TradeEpisodeORM))).scalars().all() == []
