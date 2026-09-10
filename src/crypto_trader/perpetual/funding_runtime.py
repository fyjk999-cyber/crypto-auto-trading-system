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
from crypto_trader.perpetual.funding_coverage import FundingHistoryIngestor
from crypto_trader.perpetual.funding_settlement import FundingSettlementService


@dataclass
class FundingRunReport:
    evaluated_instruments: list[str] = field(default_factory=list)
    coverage_status: dict[str, str] = field(default_factory=dict)
    settled: int = 0
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
        activity_instruments: set[str] = set()
        if self.ledger is not None:
            activity_instruments = await self.ledger.activity_instruments(
                lookback_start,
                account_id=self.account_id,
                currency=self.currency,
                end=now,
            )
        open_symbols = {
            symbol
            for symbol, position in positions.items()
            if position.quantity != 0
            and getattr(position, "instrument_type", "SPOT") == "LINEAR_PERP"
        }
        # Closed positions with verified activity still need a coverage proof
        # for the interval they were held, even though no new settlement is
        # due once the position is flat.
        for symbol in sorted(open_symbols | activity_instruments):
            position = positions.get(symbol)
            is_open = (
                position is not None
                and position.quantity != 0
                and getattr(position, "instrument_type", "SPOT") == "LINEAR_PERP"
            )
            report.evaluated_instruments.append(symbol)
            try:
                if is_open:
                    plan = (
                        await self.trade_plans.get_active_for_symbol(symbol)
                        if self.trade_plans is not None
                        else None
                    )
                else:
                    plan = (
                        await self.trade_plans.latest_for_symbol(symbol)
                        if self.trade_plans is not None
                        else None
                    )
                opened_at = _as_utc(
                    getattr(plan, "opened_at", None) if plan is not None else None
                )
                closed_at = _as_utc(
                    getattr(plan, "closed_at", None) if plan is not None else None
                )
                if is_open and opened_at is None:
                    report.skipped.append(f"{symbol}:POSITION_OPEN_TIME_UNPROVEN")
                if is_open:
                    window_start = max(lookback_start, opened_at or lookback_start)
                    window_end = now
                else:
                    # A closed position only needs coverage over its factual
                    # holding interval; including post-close history would let
                    # later funding events masquerade as unsettled hold events.
                    window_start = max(lookback_start, opened_at or lookback_start)
                    window_end = min(now, closed_at) if closed_at is not None else now
                    if window_end <= window_start:
                        continue
                coverage = await self.ingestor.ingest(
                    self.adapter,
                    instrument_id=symbol,
                    window_start=window_start,
                    window_end=window_end,
                    include_events=is_open,
                )
            except Exception as exc:  # network/API failures stay observable
                report.errors.append(f"{symbol}:{type(exc).__name__}")
                continue
            report.coverage_status[symbol] = coverage.coverage_status
            if not is_open:
                continue
            if coverage.coverage_status == "UNKNOWN":
                report.skipped.append(f"{symbol}:FUNDING_COVERAGE_UNKNOWN")
                continue
            if opened_at is None:
                continue
            instrument = instruments.get(symbol)
            contract_size = (
                instrument.contract_size
                if instrument is not None
                else position.contract_size
            )
            contract_multiplier = (
                instrument.contract_multiplier
                if instrument is not None
                else position.contract_multiplier
            )
            for event in coverage.window_events:
                try:
                    settlement_time = datetime.fromtimestamp(
                        int(event["fundingTime"]) / 1000, tz=UTC
                    )
                except (KeyError, TypeError, ValueError):
                    report.skipped.append(f"{symbol}:MALFORMED_FUNDING_EVENT")
                    continue
                if settlement_time < opened_at:
                    continue
                rate = event.get("realizedRate")
                if rate in (None, ""):
                    report.skipped.append(f"{symbol}:MISSING_FUNDING_RATE")
                    continue
                # Historical quantity must be the factual signed position at
                # each settlement instant, not the current projection amount.
                if self.order_manager is None:
                    report.skipped.append(f"{symbol}:POSITION_QUANTITY_UNAVAILABLE")
                    continue
                signed_quantity = await self.order_manager.signed_quantity_at(
                    symbol, settlement_time
                )
                if signed_quantity == 0:
                    continue
                mark_price = await self._factual_settlement_mark(
                    symbol, settlement_time
                )
                if mark_price is None:
                    report.skipped.append(f"{symbol}:SETTLEMENT_MARK_UNAVAILABLE")
                    continue
                try:
                    await self.settlement_service.settle(
                        account_id=self.account_id,
                        instrument_id=symbol,
                        settlement_timestamp=settlement_time,
                        signed_quantity=signed_quantity,
                        mark_price=mark_price,
                        funding_rate=D(rate),
                        contract_size=D(contract_size),
                        contract_multiplier=D(contract_multiplier),
                        currency=self.currency,
                    )
                except Exception as exc:
                    report.errors.append(f"{symbol}:{type(exc).__name__}")
                    continue
                report.settled += 1
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
