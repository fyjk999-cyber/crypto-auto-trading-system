"""V5 focused regressions: boundary idempotency, OKX mark contract, recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from crypto_trader.ledger.service import LedgerService
from crypto_trader.perpetual.funding_boundary import (
    FundingPublicDataBoundary,
    as_funding_boundary,
)
from crypto_trader.perpetual.funding_coverage import FundingCoverageService
from crypto_trader.perpetual.funding_runtime import (
    FundingAccountingSupervisor,
    _event_rate,
)
from crypto_trader.perpetual.funding_settlement import FundingSettlementService
from crypto_trader.persistence.models import (
    FundingEventResolutionORM,
    LedgerTransactionORM,
)
from tests.integration.test_v4_review4 import (
    FakePlans,
    MarkOnlyAdapter,
    Plan,
    RecordingIngestor,
)

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
            source="V5_FAKE",
        )

    async def get(self, order_id):
        return None


def _instruments():
    return {
        "BTCUSDT": {
            "symbol": "BTCUSDT",
            "instrument_type": "LINEAR_PERP",
            "contract_size": Decimal("0.01"),
            "contract_multiplier": Decimal("1"),
        }
    }


class PagedHistoryClient:
    """Raw-style client with per-cursor history pages and funding pages."""

    expects_canonical_symbols = True

    def __init__(self, history_pages, funding_pages=None):
        self.history_pages = list(history_pages)
        self.funding_pages = list(funding_pages or [])
        self.history_calls = []
        self.funding_calls = []

    async def get_mark_price_candles(
        self, symbol, *, bar="1H", limit=100, before=None, after=None
    ):
        return []

    async def get_history_mark_price_candles(
        self, symbol, *, bar="1H", limit=100, before=None, after=None
    ):
        self.history_calls.append((symbol, bar, before, after))
        if self.history_pages:
            return self.history_pages.pop(0)
        return []

    async def get_funding_rate_history(
        self, symbol, *, before=None, after=None, limit=100
    ):
        self.funding_calls.append((symbol, before, after))
        if self.funding_pages:
            return self.funding_pages.pop(0)
        return []


def _row(open_at: datetime, close: str, confirm="1") -> list[str]:
    return [
        str(int(open_at.timestamp() * 1000)),
        "1",
        "1",
        "1",
        close,
        confirm,
    ]


async def _paged_supervisor(database, client, plan, lookback=24):
    coverage_service = FundingCoverageService(database.session_factory)
    ledger = LedgerService(database.session_factory)
    ingestor = RecordingIngestor(coverage_service, {})
    supervisor = FundingAccountingSupervisor(
        adapter=client,
        ingestor=ingestor,
        settlement_service=FundingSettlementService(ledger),
        portfolio=EmptyPortfolio(),
        trade_plans=FakePlans([plan]),
        ledger=ledger,
        order_manager=FakeOrderManager(),
        instruments_provider=_instruments,
        lookback_hours=lookback,
    )
    return supervisor, coverage_service, ledger


async def test_as_funding_boundary_is_idempotent():
    client = MarkOnlyAdapter([], expects_canonical_symbols=False)
    first = FundingPublicDataBoundary(client)
    assert as_funding_boundary(first) is first
    assert as_funding_boundary(client) is not first
    assert first.client is client


async def test_okx_mark_candle_endpoints_and_six_field_schema(monkeypatch):
    from crypto_trader.exchange.okx import OKXAdapter, OKXDiagnosticError

    class HttpStub:
        def __init__(self):
            self.mode = "ok"
            self.seen = {}

        async def _public_request(
            self, method, path, *, params=None, headers=None, body=None
        ):
            self.seen = {"method": method, "path": path, "params": params}
            if self.mode == "ok":
                return {
                    "data": [[1789045200000, "99", "100", "98", "99.5", "1"]]
                }
            if self.mode == "malformed":
                return {"data": [["1", "2", "3", "4", "5"]]}
            return {"data": [["1", "2", "3", "4", "5", "0"]]}

    adapter = HttpStub()
    rows = await OKXAdapter.get_mark_price_candles(
        adapter, "BTC-USDT-SWAP", bar="1H", limit=10, before="1789045200001"
    )
    assert adapter.seen["path"] == "/api/v5/market/mark-price-candles"
    assert adapter.seen["params"]["instId"] == "BTC-USDT-SWAP"
    assert adapter.seen["params"]["before"] == "1789045200001"
    assert len(rows[0]) == 6

    rows = await OKXAdapter.get_history_mark_price_candles(
        adapter, "BTC-USDT-SWAP", bar="1H", limit=10, before="1789045200001"
    )
    assert adapter.seen["path"] == "/api/v5/market/history-mark-price-candles"
    assert rows[0][4] == "99.5"

    adapter.mode = "malformed"
    with pytest.raises(OKXDiagnosticError):
        await OKXAdapter.get_mark_price_candles(
            adapter, "BTC-USDT-SWAP", bar="1H"
        )

    adapter.mode = "unconfirmed"
    with pytest.raises(OKXDiagnosticError):
        await OKXAdapter.get_mark_price_candles(
            adapter, "BTC-USDT-SWAP", bar="1H"
        )


async def test_historical_recovery_120h_and_10d(database):
    for hours_ago, label in ((120, "120h"), (240, "10d")):
        event = NOW - timedelta(hours=hours_ago)
        plan = Plan(
            f"plan-{label}",
            "BTCUSDT",
            event - timedelta(hours=2),
            event + timedelta(hours=1),
        )
        client = PagedHistoryClient(
            history_pages=[[_row(event - timedelta(hours=1), "100")]]
        )
        supervisor, coverage_service, ledger = await _paged_supervisor(
            database, client, plan
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
        async with database.session_factory() as session:
            before = (
                await session.execute(
                    select(LedgerTransactionORM).where(
                        LedgerTransactionORM.entry_type.in_(
                            ("FUNDING_RECEIPT", "FUNDING_PAYMENT")
                        )
                    )
                )
            ).scalars().all()
        report = await supervisor.run_once(now=NOW)
        assert report.settled == 1, label
        second = await supervisor.run_once(now=NOW)
        assert second.settled == 0, label
        async with database.session_factory() as session:
            after = (
                await session.execute(
                    select(LedgerTransactionORM).where(
                        LedgerTransactionORM.entry_type.in_(
                            ("FUNDING_RECEIPT", "FUNDING_PAYMENT")
                        )
                    )
                )
            ).scalars().all()
        assert len(after) == len(before) + 1, label


async def test_history_recovery_uses_second_page_and_cursor(database):
    event = NOW - timedelta(hours=120)
    plan = Plan(
        "plan-page2", "BTCUSDT", event - timedelta(hours=2), event + timedelta(hours=1)
    )
    old_page = [_row(event - timedelta(hours=6), "99")]
    target_page = [_row(event - timedelta(hours=1), "100")]
    client = PagedHistoryClient(history_pages=[old_page, target_page])
    supervisor, coverage_service, _ = await _paged_supervisor(database, client, plan)
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
    assert len(client.history_calls) == 2
    first_before = int(client.history_calls[0][2])
    second_before = int(client.history_calls[1][2])
    assert first_before > int(event.timestamp() * 1000)
    assert second_before < first_before


async def test_history_target_unavailable_stays_mark_unavailable(database):
    event = NOW - timedelta(hours=120)
    plan = Plan(
        "plan-missing", "BTCUSDT", event - timedelta(hours=2), event + timedelta(hours=1)
    )
    client = PagedHistoryClient(history_pages=[[_row(event - timedelta(hours=7), "99")]])
    supervisor, coverage_service, _ = await _paged_supervisor(database, client, plan)
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
    assert report.settled == 0
    async with database.session_factory() as session:
        resolution = (
            await session.execute(select(FundingEventResolutionORM))
        ).scalar_one()
    assert resolution.status == "MARK_UNAVAILABLE"


async def test_funding_rate_exact_cursor_and_pagination(database):
    target = NOW - timedelta(hours=48)
    plan = Plan("rate-plan", "BTCUSDT", target - timedelta(hours=2), target + timedelta(hours=1))
    older = [
        {
            "fundingTime": str(int((target - timedelta(hours=1)).timestamp() * 1000)),
            "realizedRate": "0.0009",
        }
    ]
    exact = [
        {
            "fundingTime": str(int(target.timestamp() * 1000)),
            "realizedRate": "0.001",
        }
    ]
    client = PagedHistoryClient(history_pages=[], funding_pages=[older, exact])
    supervisor, coverage_service, _ = await _paged_supervisor(database, client, plan)
    rate = await supervisor._funding_rate_at("BTCUSDT", target)
    assert rate == Decimal("0.001")
    assert len(client.funding_calls) == 2
    assert client.funding_calls[0][2] is None  # after never passed


async def test_funding_rate_missing_and_malformed_are_unproven(database):
    target = NOW - timedelta(hours=48)
    plan = Plan("rate-bad", "BTCUSDT", target - timedelta(hours=2), target + timedelta(hours=1))
    for page in (
        [{"fundingTime": str(int(target.timestamp() * 1000))}],
        [
            {
                "fundingTime": str(int(target.timestamp() * 1000)),
                "realizedRate": "not-a-number",
            }
        ],
    ):
        client = PagedHistoryClient(history_pages=[], funding_pages=[page])
        supervisor, coverage_service, _ = await _paged_supervisor(
            database, client, plan
        )
        assert await supervisor._funding_rate_at("BTCUSDT", target) is None


async def test_funding_rate_zero_is_proven_zero_and_event_rate_none(database):
    target = NOW - timedelta(hours=48)
    plan = Plan("rate-zero", "BTCUSDT", target - timedelta(hours=2), target + timedelta(hours=1))
    client = PagedHistoryClient(
        history_pages=[],
        funding_pages=[
            [
                {
                    "fundingTime": str(int(target.timestamp() * 1000)),
                    "realizedRate": "0",
                }
            ]
        ],
    )
    supervisor, coverage_service, _ = await _paged_supervisor(database, client, plan)
    assert await supervisor._funding_rate_at("BTCUSDT", target) == Decimal("0")

    assert _event_rate({"realizedRate": "0"}) == Decimal("0")
    assert _event_rate({"realizedRate": ""}) is None
    assert _event_rate({"realizedRate": "bad"}) is None
    assert _event_rate({"realizedRate": None}) is None
