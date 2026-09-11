"""V6 focused regressions: confirm pages, cursor direction, negative rates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.ledger.service import LedgerService
from crypto_trader.perpetual.funding_coverage import FundingCoverageService
from crypto_trader.perpetual.funding_runtime import (
    FundingAccountingSupervisor,
    _event_rate,
)
from crypto_trader.perpetual.funding_settlement import FundingSettlementService
from crypto_trader.persistence.models import (
    FundingEventResolutionORM,
    LedgerEntryORM,
    LedgerTransactionORM,
)
from tests.integration.test_v3_review3 import _add_verified_fill
from tests.integration.test_v4_review4 import FakePlans, Plan, RecordingIngestor

NOW = datetime(2026, 9, 12, 15, tzinfo=UTC)


class EmptyPortfolio:
    async def get_positions(self):
        return {}


class FakeOrderManager:
    async def historical_quantity_at(self, *, account_id, symbol, at, currency="USDT"):
        from crypto_trader.order.provenance import (
            HistoricalQuantityProvenance,
            HistoricalQuantityStatus,
        )

        return HistoricalQuantityProvenance(
            account_id=account_id,
            instrument_id=symbol,
            settlement_timestamp=at,
            status=HistoricalQuantityStatus.PROVEN_VALUE,
            quantity=Decimal("1"),
            source="V6_FAKE",
        )

    async def get(self, order_id):
        return None


def _instruments(symbol="BTCUSDT"):
    return {
        symbol: {
            "symbol": symbol,
            "instrument_type": "LINEAR_PERP",
            "contract_size": Decimal("0.01"),
            "contract_multiplier": Decimal("1"),
        }
    }


class CursorAwareMarkProvider:
    """OKX cursor semantics: before=newer, after=older; newest rows first."""

    expects_canonical_symbols = True

    def __init__(self, rows, *, page_limit=100):
        self.rows = sorted(rows, key=lambda row: int(row[0]), reverse=True)
        self.page_limit = page_limit
        self.calls = []

    def _page(self, before, after, limit):
        selected = self.rows
        if before is not None:
            selected = [row for row in selected if int(row[0]) > int(before)]
        if after is not None:
            selected = [row for row in selected if int(row[0]) < int(after)]
        return selected[: min(limit, self.page_limit)]

    async def get_mark_price_candles(
        self, symbol, *, bar="1H", limit=100, before=None, after=None
    ):
        self.calls.append(("recent", symbol, before, after))
        return list(reversed(self._page(before, after, limit)))

    async def get_history_mark_price_candles(
        self, symbol, *, bar="1H", limit=100, before=None, after=None
    ):
        self.calls.append(("history", symbol, before, after))
        return list(reversed(self._page(before, after, limit)))


class CursorAwareFundingProvider:
    """OKX cursor semantics: before=newer, after=older; newest rows first."""

    expects_canonical_symbols = True

    def __init__(self, events, *, page_limit=100):
        self.events = sorted(
            events, key=lambda row: int(row["fundingTime"]), reverse=True
        )
        self.page_limit = page_limit
        self.calls = []

    async def get_funding_rate_history(
        self, symbol, *, before=None, after=None, limit=100
    ):
        self.calls.append((symbol, before, after))
        selected = self.events
        if before is not None:
            selected = [
                row for row in selected if int(row["fundingTime"]) > int(before)
            ]
        if after is not None:
            selected = [
                row for row in selected if int(row["fundingTime"]) < int(after)
            ]
        return selected[: min(limit, self.page_limit)]

    async def get_mark_price_candles(self, *args, **kwargs):
        return []

    async def get_history_mark_price_candles(self, *args, **kwargs):
        return []


def _mark_row(open_at: datetime, close: str, confirm="1") -> list[str]:
    return [
        str(int(open_at.timestamp() * 1000)),
        "1",
        "1",
        "1",
        close,
        confirm,
    ]


def _event_row(stamp: datetime, rate: str) -> dict:
    return {
        "fundingTime": str(int(stamp.timestamp() * 1000)),
        "realizedRate": rate,
    }


async def _supervisor(database, client, plans, instruments=None, events=None):
    coverage_service = FundingCoverageService(database.session_factory)
    ledger = LedgerService(database.session_factory)
    ingestor = RecordingIngestor(coverage_service, events or {})
    supervisor = FundingAccountingSupervisor(
        adapter=client,
        ingestor=ingestor,
        settlement_service=FundingSettlementService(ledger),
        portfolio=EmptyPortfolio(),
        trade_plans=FakePlans(plans),
        ledger=ledger,
        order_manager=FakeOrderManager(),
        instruments_provider=lambda: instruments or _instruments(),
        lookback_hours=24,
    )
    return supervisor, coverage_service, ledger


async def test_event_rate_accepts_negative_realized_rate():
    assert _event_rate({"realizedRate": "0.001"}) == Decimal("0.001")
    assert _event_rate({"realizedRate": "-0.001"}) == Decimal("-0.001")
    assert _event_rate({"realizedRate": "0"}) == Decimal("0")
    assert _event_rate({"realizedRate": ""}) is None
    assert _event_rate({"realizedRate": "bad"}) is None
    assert _event_rate({"realizedRate": None}) is None


async def test_mark_page_unconfirmed_head_keeps_confirmed_history(database):
    event = NOW - timedelta(hours=2)
    plan = Plan("confirm-plan", "BTCUSDT", event - timedelta(hours=2), NOW)
    rows = [
        _mark_row(event, "999", confirm="0"),
        _mark_row(event - timedelta(hours=1), "100", confirm="1"),
    ]
    client = CursorAwareMarkProvider(rows)
    supervisor, _, ledger = await _supervisor(
        database, client, [plan], events={"BTCUSDT": [(event, "0.001")]}
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 1
    async with database.session_factory() as session:
        txns = (
            await session.execute(
                select(LedgerTransactionORM).where(
                    LedgerTransactionORM.entry_type.in_(
                        ("FUNDING_RECEIPT", "FUNDING_PAYMENT")
                    )
                )
            )
        ).scalars().all()
    assert len(txns) == 1
    async with database.session_factory() as session:
        resolution = (
            await session.execute(select(FundingEventResolutionORM))
        ).scalar_one()
    assert resolution.mark_price == Decimal("100")
    assert resolution.status == "SETTLED"


async def test_all_unconfirmed_marks_are_unavailable(database):
    event = NOW - timedelta(hours=2)
    plan = Plan("all-unconfirmed", "BTCUSDT", event - timedelta(hours=2), NOW)
    client = CursorAwareMarkProvider([_mark_row(event, "999", confirm="0")])
    supervisor, _, ledger = await _supervisor(database, client, [plan])
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 0
    async with database.session_factory() as session:
        assert (
            await session.execute(select(LedgerTransactionORM))
        ).scalars().all() == []


async def test_okx_funding_rate_history_http_contract(monkeypatch):
    from crypto_trader.exchange.okx import OKXAdapter

    class HttpStub:
        def __init__(self):
            self.seen = {}

        async def _public_request(
            self, method, path, *, params=None, headers=None, body=None
        ):
            self.seen = {"method": method, "path": path, "params": params}
            return {
                "data": [
                    {"fundingTime": "1789100000000", "realizedRate": "-0.001"}
                ]
            }

    adapter = HttpStub()
    rows = await OKXAdapter.get_funding_rate_history(
        adapter,
        "BTC-USDT-SWAP",
        before=None,
        after="1789100000001",
        limit=50,
    )
    assert adapter.seen["path"] == "/api/v5/public/funding-rate-history"
    assert adapter.seen["params"]["instId"] == "BTC-USDT-SWAP"
    assert adapter.seen["params"]["after"] == "1789100000001"
    assert "before" not in adapter.seen["params"]
    assert rows[0]["realizedRate"] == "-0.001"


async def test_historical_mark_cursor_direction_and_10d(database):
    for hours_ago in (120, 240):
        event = NOW - timedelta(hours=hours_ago)
        plan = Plan(
            f"dir-{hours_ago}",
            "BTCUSDT",
            event - timedelta(hours=2),
            event + timedelta(hours=1),
        )
        # Includes a newer unconfirmed candle; correct `after` cursor reaches
        # the older confirmed candle. Reversed cursor direction would not.
        client = CursorAwareMarkProvider(
            [
                _mark_row(event, "999", confirm="0"),
                _mark_row(event - timedelta(hours=1), "100", confirm="1"),
            ]
        )
        supervisor, coverage_service, ledger = await _supervisor(
            database, client, [plan]
        )
        await coverage_service.record_event_resolution(
            account_id="default",
            instrument_id="BTCUSDT",
            settlement_timestamp=event,
            status="MARK_UNAVAILABLE",
            quantity=Decimal("1"),
            funding_rate=Decimal("0.001"),
            trade_plan_id=plan.trade_plan_id,
            reason="NO_CLOSED_MARK_PRICE_CANDLE",
        )
        report = await supervisor.run_once(now=NOW)
        assert report.settled == 1
        assert any(call[0] == "history" and call[3] is not None for call in client.calls)


async def test_historical_mark_second_page(database):
    event = NOW - timedelta(hours=120)
    plan = Plan("page2", "BTCUSDT", event - timedelta(hours=2), event + timedelta(hours=1))
    client = CursorAwareMarkProvider(
        [
            _mark_row(event, "999", confirm="1"),
            _mark_row(event - timedelta(hours=1), "100", confirm="1"),
        ],
        page_limit=1,
    )
    supervisor, coverage_service, _ = await _supervisor(database, client, [plan])
    await coverage_service.record_event_resolution(
        account_id="default",
        instrument_id="BTCUSDT",
        settlement_timestamp=event,
        status="MARK_UNAVAILABLE",
        quantity=Decimal("1"),
        funding_rate=Decimal("0.001"),
        trade_plan_id=plan.trade_plan_id,
        reason="NO_CLOSED_MARK_PRICE_CANDLE",
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 1
    history_calls = [call for call in client.calls if call[0] == "history"]
    assert len(history_calls) >= 2
    assert int(history_calls[0][3]) > int(history_calls[1][3])


async def test_funding_rate_cursor_aware_exact_target(database):
    target = NOW - timedelta(hours=48)
    plan = Plan("rate", "BTCUSDT", target - timedelta(hours=2), target + timedelta(hours=1))
    events = [
        _event_row(target + timedelta(minutes=30), "0.5"),
        _event_row(target, "-0.001"),
        _event_row(target - timedelta(hours=1), "0.002"),
    ]
    client = CursorAwareFundingProvider(events)
    supervisor, _, _ = await _supervisor(database, client, [plan])
    rate = await supervisor._funding_rate_at("BTCUSDT", target)
    assert rate == Decimal("-0.001")
    assert client.calls[0][1] is None
    assert int(client.calls[0][2]) == int(target.timestamp() * 1000) + 1


async def test_funding_rate_missing_is_unproven(database):
    target = NOW - timedelta(hours=48)
    plan = Plan("rate-missing", "BTCUSDT", target - timedelta(hours=2), target + timedelta(hours=1))
    client = CursorAwareFundingProvider(
        [_event_row(target - timedelta(minutes=30), "0.001")]
    )
    supervisor, coverage_service, ledger = await _supervisor(database, client, [plan])
    assert await supervisor._funding_rate_at("BTCUSDT", target) is None
    await coverage_service.record_event_resolution(
        account_id="default",
        instrument_id="BTCUSDT",
        settlement_timestamp=target,
        status="MARK_UNAVAILABLE",
        quantity=Decimal("1"),
        funding_rate=None,
        trade_plan_id=plan.trade_plan_id,
        reason="NO_CLOSED_MARK_PRICE_CANDLE",
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 0
    async with database.session_factory() as session:
        resolution = (
            await session.execute(select(FundingEventResolutionORM))
        ).scalar_one()
    assert resolution.status == "UNPROVEN"
    assert resolution.reason == "FUNDING_RATE_UNAVAILABLE"


@pytest.mark.parametrize(
    ("direction", "rate", "entry_type", "direction_name"),
    [
        (Decimal("1"), Decimal("0.001"), "FUNDING_PAYMENT", "LONG_POSITIVE"),
        (Decimal("1"), Decimal("-0.001"), "FUNDING_RECEIPT", "LONG_NEGATIVE"),
        (Decimal("-1"), Decimal("0.001"), "FUNDING_RECEIPT", "SHORT_POSITIVE"),
        (Decimal("-1"), Decimal("-0.001"), "FUNDING_PAYMENT", "SHORT_NEGATIVE"),
    ],
)
async def test_negative_funding_rate_direction_matrix(
    database, direction, rate, entry_type, direction_name
):
    ledger = LedgerService(database.session_factory)
    settlement = FundingSettlementService(ledger)
    amount = await settlement.settle(
        account_id="default",
        instrument_id="BTCUSDT",
        settlement_timestamp=NOW,
        signed_quantity=direction,
        mark_price=Decimal("100"),
        funding_rate=rate,
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
    )
    assert amount != 0
    async with database.session_factory() as session:
        entry = (
            await session.execute(
                select(LedgerEntryORM).where(
                    LedgerEntryORM.account == entry_type,
                    LedgerEntryORM.currency == "USDT",
                )
            )
        ).scalars().first()
    assert entry is not None, direction_name
    replay = await settlement.settle(
        account_id="default",
        instrument_id="BTCUSDT",
        settlement_timestamp=NOW,
        signed_quantity=direction,
        mark_price=Decimal("100"),
        funding_rate=rate,
        contract_size=Decimal("0.01"),
        contract_multiplier=Decimal("1"),
    )
    assert replay == amount
    async with database.session_factory() as session:
        count = len(
            (
                await session.execute(
                    select(LedgerTransactionORM).where(
                        LedgerTransactionORM.entry_type == entry_type
                    )
                )
            ).scalars().all()
        )
    assert count == 1, direction_name


class RawProductionOkxClient:
    """Raw venue client: expects OKX instIds, records them, cursor-aware."""

    def __init__(self, funding_events, mark_rows):
        self.funding_events = sorted(
            funding_events, key=lambda row: int(row["fundingTime"]), reverse=True
        )
        self.mark_rows = sorted(
            mark_rows, key=lambda row: int(row[0]), reverse=True
        )
        self.received = []

    async def get_funding_rate_history(
        self, symbol, *, before=None, after=None, limit=100
    ):
        self.received.append(("funding", symbol, before, after))
        selected = self.funding_events
        if before is not None:
            selected = [
                row for row in selected if int(row["fundingTime"]) > int(before)
            ]
        if after is not None:
            selected = [
                row for row in selected if int(row["fundingTime"]) < int(after)
            ]
        return selected[:limit]

    async def get_mark_price_candles(
        self, symbol, *, bar="1H", limit=100, before=None, after=None
    ):
        self.received.append(("mark", symbol, before, after))
        return list(self.mark_rows[:limit])

    async def get_history_mark_price_candles(
        self, symbol, *, bar="1H", limit=100, before=None, after=None
    ):
        self.received.append(("history", symbol, before, after))
        selected = self.mark_rows
        if before is not None:
            selected = [row for row in selected if int(row[0]) > int(before)]
        if after is not None:
            selected = [row for row in selected if int(row[0]) < int(after)]
        return list(selected[:limit])


@pytest.mark.parametrize("rate", ["0.001", "-0.001"])
async def test_production_paper_real_market_funding_public_chain(
    database, monkeypatch, rate
):
    from datetime import timedelta

    from crypto_trader.persistence.models import TradePlanORM
    from crypto_trader.runtime.bootstrap import build_system

    target = NOW - timedelta(hours=2)
    opened = target - timedelta(hours=2)
    closed = NOW
    raw_client = RawProductionOkxClient(
        funding_events=[
            _event_row(target, rate),
            _event_row(target - timedelta(hours=8), "0.002"),
        ],
        mark_rows=[
            _mark_row(target, "999", confirm="0"),
            _mark_row(target - timedelta(hours=1), "100", confirm="1"),
        ],
    )

    class FakeFeed:
        def __init__(self):
            self.client = raw_client

        async def warmup(self, *args, **kwargs):
            return None

    class FakePaperAdapter:
        def __init__(self, initial_balances):
            self.feed = FakeFeed()
            self.instruments = _instruments("BTCUSDT")

    import crypto_trader.runtime.bootstrap as bootstrap

    monkeypatch.setattr(bootstrap, "PaperRealMarketAdapter", FakePaperAdapter)
    from crypto_trader.config import Settings

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
        await _add_verified_fill(
            bundle.database,
            bundle.ledger,
            fill_id="prod_chain_fill",
            order_id="prod_chain_order",
            account_id="default",
            symbol="BTCUSDT",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("100"),
            at=opened,
        )
        async with bundle.database.session_factory() as session:
            session.add(
                TradePlanORM(
                    trade_plan_id="prod_chain_plan",
                    decision_id="prod_chain_decision",
                    symbol="BTCUSDT",
                    direction="LONG",
                    state="CLOSED",
                    thesis="v6 production chain",
                    requested_quantity=Decimal("1"),
                    order_id="prod_chain_order",
                    exit_decision_id="prod_chain_exit",
                    risk_decision_id="prod_chain_risk",
                    opened_at=opened,
                    closed_at=closed,
                )
            )
            await session.commit()

        supervisor = bundle.engine.funding_supervisor
        first = await supervisor.run_once(now=NOW)
        second = await supervisor.run_once(now=NOW)
        assert first.settled == 1
        assert second.settled == 0
        assert any(
            call[0] == "funding" and call[1] == "BTC-USDT-SWAP"
            for call in raw_client.received
        )
        assert any(
            call[0] == "mark" and call[1] == "BTC-USDT-SWAP"
            for call in raw_client.received
        )
        async with bundle.database.session_factory() as session:
            txns = (
                await session.execute(
                    select(LedgerTransactionORM).where(
                        LedgerTransactionORM.entry_type.in_(
                            ("FUNDING_RECEIPT", "FUNDING_PAYMENT")
                        )
                    )
                )
            ).scalars().all()
        assert len(txns) == 1
        assert txns[0].instrument_id == "BTCUSDT"
    finally:
        await bundle.database.close()


async def test_zero_rate_is_proven_noop(database):
    target = NOW - timedelta(hours=48)
    plan = Plan("zero", "BTCUSDT", target - timedelta(hours=2), target + timedelta(hours=1))
    client = CursorAwareFundingProvider([_event_row(target, "0")])
    supervisor, coverage_service, ledger = await _supervisor(database, client, [plan])
    await coverage_service.record_event_resolution(
        account_id="default",
        instrument_id="BTCUSDT",
        settlement_timestamp=target,
        status="MARK_UNAVAILABLE",
        quantity=Decimal("1"),
        funding_rate=Decimal("0"),
        trade_plan_id=plan.trade_plan_id,
        reason="NO_CLOSED_MARK_PRICE_CANDLE",
    )
    report = await supervisor.run_once(now=NOW)
    assert report.settled == 0
    async with database.session_factory() as session:
        resolution = (
            await session.execute(select(FundingEventResolutionORM))
        ).scalar_one()
    assert resolution.status == "NO_OP"
