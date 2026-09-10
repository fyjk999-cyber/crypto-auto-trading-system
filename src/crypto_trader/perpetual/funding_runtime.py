"""Formal PAPER funding accounting chain.

OKX public funding history -> coverage proof -> PAPER_DERIVED settlement ->
canonical ledger -> scoped PnL provenance -> Risk.

The supervisor never invents a mark price. If the factual settlement-time
price is unavailable, the event is skipped and daily PnL stays incomplete
(fail closed) instead of booking a synthetic amount.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from crypto_trader.domain.money import D
from crypto_trader.order.provenance import HistoricalQuantityStatus
from crypto_trader.perpetual.funding_coverage import FundingHistoryIngestor
from crypto_trader.perpetual.funding_settlement import (
    FundingSettlementService,
    canonical_utc_timestamp_text,
)


@dataclass
class FundingRunReport:
    evaluated_instruments: list[str] = field(default_factory=list)
    coverage_status: dict[str, str] = field(default_factory=dict)
    lifecycle_coverage: dict[str, str] = field(default_factory=dict)
    settled: int = 0
    no_op: int = 0
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class FundingAccountingSupervisor:
    """Runs the formal public-history -> PAPER ledger funding chain."""

    name = "paper_funding_accounting"

    def __init__(
        self,
        *,
        adapter,
        ingestor: FundingHistoryIngestor,
        settlement_service: FundingSettlementService,
        portfolio,
        trade_plans=None,
        ledger=None,
        order_manager=None,
        trade_episodes=None,
        instruments_provider: Callable[[], Mapping[str, Any]] | None = None,
        account_id: str = "default",
        currency: str = "USDT",
        lookback_hours: int = 24,
    ) -> None:
        self.adapter = adapter
        self.ingestor = ingestor
        self.settlement_service = settlement_service
        self.portfolio = portfolio
        self.trade_plans = trade_plans
        self.ledger = ledger
        self.order_manager = order_manager
        self.trade_episodes = trade_episodes
        self.instruments_provider = instruments_provider or (lambda: {})
        self.account_id = account_id
        self.currency = currency
        self.lookback_hours = max(1, lookback_hours)

    async def run_once(self, *, now: datetime | None = None) -> FundingRunReport:
        report = FundingRunReport()
        if self.adapter is None:
            report.errors.append("NO_PUBLIC_FUNDING_ADAPTER")
            return report
        now = now or datetime.now(UTC)
        lookback_start = now - timedelta(hours=self.lookback_hours)
        positions = await self.portfolio.get_positions()
        instruments = self.instruments_provider() or {}
        coverage_service = getattr(self.ingestor, "coverage_service", None)
        existing_resolutions: dict[datetime, str] = {}
        lifecycle_specs: list[tuple[object, str, datetime, datetime]] = []
        if self.trade_plans is not None:
            plans = await self.trade_plans.lifecycles_overlapping(
                lookback_start, now
            )
            for plan in plans:
                opened_at = _as_utc(getattr(plan, "opened_at", None))
                closed_at = _as_utc(getattr(plan, "closed_at", None))
                if opened_at is None:
                    report.skipped.append(
                        f"{getattr(plan, 'symbol', 'UNKNOWN')}:POSITION_OPEN_TIME_UNPROVEN"
                    )
                    continue
                window_start = max(lookback_start, opened_at)
                if closed_at is None:
                    window_end = now
                else:
                    # Include a funding event exactly at the factual close.
                    window_end = min(now, closed_at + timedelta(microseconds=1))
                if window_end <= window_start:
                    continue
                lifecycle_specs.append(
                    (plan, str(getattr(plan, "symbol", "")), window_start, window_end)
                )
        # Open positions without a durable plan still need coverage, but their
        # events cannot be attributed to a lifecycle and settlement stays
        # blocked until lineage exists.
        planned_symbols = {
            symbol for plan, symbol, *_ in lifecycle_specs if plan is not None
        }
        for symbol, position in sorted(positions.items()):
            if position.quantity == 0:
                continue
            if getattr(position, "instrument_type", "SPOT") != "LINEAR_PERP":
                continue
            if symbol in planned_symbols:
                continue
            report.skipped.append(f"{symbol}:LIFECYCLE_PLAN_MISSING")
            lifecycle_specs.append((None, symbol, lookback_start, now))

        covered_unplanned = {
            str(item[1]) for item in lifecycle_specs if item[0] is None
        }
        if self.ledger is not None:
            activity_instruments = await self.ledger.activity_instruments(
                lookback_start,
                account_id=self.account_id,
                currency=self.currency,
                end=now,
            )
            for symbol in sorted(
                activity_instruments - planned_symbols - covered_unplanned
            ):
                lifecycle_specs.append((None, symbol, lookback_start, now))

        for plan, symbol, window_start, window_end in lifecycle_specs:
            plan_id = getattr(plan, "trade_plan_id", None)
            report.evaluated_instruments.append(symbol)
            try:
                coverage = await self.ingestor.ingest(
                    self.adapter,
                    instrument_id=symbol,
                    window_start=window_start,
                    window_end=window_end,
                    include_events=True,
                )
            except Exception as exc:
                report.errors.append(f"{symbol}:{type(exc).__name__}")
                continue
            report.coverage_status[symbol] = coverage.coverage_status
            if plan_id is not None:
                report.lifecycle_coverage[plan_id] = coverage.coverage_status
            if coverage.coverage_status == "UNKNOWN":
                report.skipped.append(f"{symbol}:FUNDING_COVERAGE_UNKNOWN")
                continue
            if plan is None:
                continue
            opened_at = _as_utc(getattr(plan, "opened_at", None))
            closed_at = _as_utc(getattr(plan, "closed_at", None))
            if coverage_service is not None:
                existing_resolutions = {
                    resolution.settlement_timestamp: resolution.status
                    for resolution in await coverage_service.event_resolutions(
                        account_id=self.account_id,
                        instrument_id=symbol,
                        currency=self.currency,
                    )
                }
            for event in coverage.window_events:
                settlement_time = _event_time(event)
                if settlement_time is None:
                    report.skipped.append(f"{symbol}:MALFORMED_FUNDING_EVENT")
                    continue
                if opened_at is not None and settlement_time <= opened_at:
                    continue
                if closed_at is not None and settlement_time > closed_at:
                    continue
                if self.order_manager is None:
                    report.skipped.append(
                        f"{symbol}:POSITION_QUANTITY_AT_SETTLEMENT_UNPROVEN"
                    )
                    continue
                provenance = await self.order_manager.historical_quantity_at(
                    account_id=self.account_id,
                    symbol=symbol,
                    at=settlement_time,
                    currency=self.currency,
                )
                if provenance.status == HistoricalQuantityStatus.UNPROVEN:
                    if coverage_service is not None:
                        await coverage_service.record_event_resolution(
                            account_id=self.account_id,
                            instrument_id=symbol,
                            settlement_timestamp=settlement_time,
                            currency=self.currency,
                            status="UNPROVEN",
                            funding_rate=_event_rate(event),
                            reason=provenance.reason or "UNPROVEN",
                        )
                    report.skipped.append(
                        f"{symbol}:POSITION_QUANTITY_AT_SETTLEMENT_UNPROVEN"
                    )
                    continue
                if provenance.status == HistoricalQuantityStatus.PROVEN_ZERO:
                    if coverage_service is not None:
                        await coverage_service.record_event_resolution(
                            account_id=self.account_id,
                            instrument_id=symbol,
                            settlement_timestamp=settlement_time,
                            currency=self.currency,
                            status="NO_OP",
                            quantity=Decimal("0"),
                            funding_rate=_event_rate(event),
                            reason="QUANTITY_ZERO",
                        )
                    report.no_op += 1
                    continue
                if existing_resolutions.get(settlement_time) in {"SETTLED", "NO_OP"}:
                    continue
                quantity = provenance.quantity or Decimal("0")
                rate = _event_rate(event)
                if rate == 0 or quantity == 0:
                    if coverage_service is not None:
                        await coverage_service.record_event_resolution(
                            account_id=self.account_id,
                            instrument_id=symbol,
                            settlement_timestamp=settlement_time,
                            currency=self.currency,
                            status="NO_OP",
                            quantity=quantity,
                            funding_rate=rate,
                            reason="ZERO_AMOUNT",
                        )
                    report.no_op += 1
                    continue
                mark_price = await self._factual_settlement_mark(
                    symbol, settlement_time
                )
                if mark_price is None:
                    if coverage_service is not None:
                        await coverage_service.record_event_resolution(
                            account_id=self.account_id,
                            instrument_id=symbol,
                            settlement_timestamp=settlement_time,
                            currency=self.currency,
                            status="MARK_UNAVAILABLE",
                            quantity=quantity,
                            funding_rate=rate,
                            reason="NO_CLOSED_CANDLE",
                        )
                    report.skipped.append(f"{symbol}:SETTLEMENT_MARK_UNAVAILABLE")
                    continue
                instrument = instruments.get(symbol)
                position = positions.get(symbol)
                contract_size = (
                    instrument.contract_size
                    if instrument is not None
                    else getattr(position, "contract_size", Decimal("1"))
                )
                contract_multiplier = (
                    instrument.contract_multiplier
                    if instrument is not None
                    else getattr(position, "contract_multiplier", Decimal("1"))
                )
                try:
                    await self.settlement_service.settle(
                        account_id=self.account_id,
                        instrument_id=symbol,
                        settlement_timestamp=settlement_time,
                        signed_quantity=quantity,
                        mark_price=mark_price,
                        funding_rate=rate,
                        contract_size=D(contract_size),
                        contract_multiplier=D(contract_multiplier),
                        currency=self.currency,
                    )
                except Exception as exc:
                    report.errors.append(f"{symbol}:{type(exc).__name__}")
                    continue
                transaction_id = None
                if self.ledger is not None:
                    transaction_id = await self.ledger.transaction_id_for_event(
                        _canonical_event_id(
                            self.account_id, symbol, settlement_time
                        )
                    )
                if coverage_service is not None:
                    await coverage_service.record_event_resolution(
                        account_id=self.account_id,
                        instrument_id=symbol,
                        settlement_timestamp=settlement_time,
                        currency=self.currency,
                        status="SETTLED",
                        quantity=quantity,
                        mark_price=mark_price,
                        funding_rate=rate,
                        ledger_transaction_id=transaction_id,
                        reason=None,
                    )
                report.settled += 1
        if self.trade_episodes is not None:
            try:
                await self.trade_episodes.materialize_pending_closed()
            except Exception as exc:
                report.errors.append(f"EPISODE_RECOVERY:{type(exc).__name__}")
        return report

    async def _factual_settlement_mark(
        self, symbol: str, settlement_time: datetime
    ) -> Decimal | None:
        """Use the close of a candle already CLOSED at settlement.

        A candle whose close is later than the settlement instant is lookahead
        and must never be used. Try 1-minute candles first for recent
        settlements, then 1-hour candles for older ones.
        """
        get_candles = getattr(self.adapter, "get_candles", None)
        if not callable(get_candles):
            return None
        target_ms = int(settlement_time.timestamp() * 1000)
        for bar, interval_ms, tolerance_ms in (
            ("1m", 60_000, 60_000),
            ("1H", 3_600_000, 3_600_000),
        ):
            try:
                rows = await get_candles(symbol, bar=bar, limit=100)
            except Exception:
                continue
            best: tuple[int, Decimal] | None = None
            for row in rows or []:
                try:
                    open_time_ms = int(row[0])
                    close = D(row[4])
                except (IndexError, TypeError, ValueError):
                    continue
                close_time_ms = open_time_ms + interval_ms
                if close_time_ms > target_ms:
                    continue
                if best is None or close_time_ms > best[0]:
                    best = (close_time_ms, close)
            if best is None:
                continue
            if target_ms - best[0] > tolerance_ms:
                continue
            return best[1]
        return None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _event_time(event: dict) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(event["fundingTime"]) / 1000, tz=UTC)
    except (KeyError, TypeError, ValueError):
        return None


def _event_rate(event: dict) -> Decimal:
    raw = event.get("realizedRate")
    if raw in (None, ""):
        return Decimal("0")
    try:
        return D(raw)
    except Exception:
        return Decimal("0")


def _canonical_event_id(
    account_id: str, instrument_id: str, settlement_time: datetime
) -> str:
    return (
        f"{account_id}|{instrument_id}|"
        f"{canonical_utc_timestamp_text(settlement_time)}"
    )
