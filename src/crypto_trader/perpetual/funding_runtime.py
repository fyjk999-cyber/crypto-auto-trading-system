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
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.order.provenance import HistoricalQuantityStatus
from crypto_trader.perpetual.contract_spec import (
    ContractSpecProvenance,
    spec_from_instrument,
    spec_from_order_metadata,
)
from crypto_trader.perpetual.funding_boundary import (
    FundingSymbolMappingError,
    as_funding_boundary,
)
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
        symbol_mapper: SymbolMapper | None = None,
    ) -> None:
        self.adapter = adapter
        self.public_data = as_funding_boundary(
            adapter, symbol_mapper=symbol_mapper
        )
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
        if self.public_data is None:
            report.errors.append("NO_PUBLIC_FUNDING_ADAPTER")
            return report
        now = now or datetime.now(UTC)
        lookback_start = now - timedelta(hours=self.lookback_hours)
        positions = await self.portfolio.get_positions()
        instruments = self.instruments_provider() or {}
        coverage_service = getattr(self.ingestor, "coverage_service", None)

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
                    window_end = min(now, closed_at + timedelta(microseconds=1))
                if window_end <= window_start:
                    continue
                lifecycle_specs.append(
                    (plan, str(getattr(plan, "symbol", "")), window_start, window_end)
                )

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

        existing_resolutions: dict[datetime, str] = {}
        for plan, symbol, window_start, window_end in lifecycle_specs:
            plan_id = getattr(plan, "trade_plan_id", None)
            report.evaluated_instruments.append(symbol)
            try:
                self.public_data.venue_symbol(symbol)
            except FundingSymbolMappingError as exc:
                report.errors.append(f"{symbol}:SYMBOL_MAPPING_FAILED")
                report.skipped.append(f"{symbol}:SYMBOL_MAPPING_FAILED:{type(exc).__name__}")
                continue
            try:
                coverage = await self.ingestor.ingest(
                    self.public_data,
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
                existing_resolutions = await self._resolution_status_map(
                    coverage_service, symbol
                )
            for event in coverage.window_events:
                settlement_time = _event_time(event)
                if settlement_time is None:
                    report.skipped.append(f"{symbol}:MALFORMED_FUNDING_EVENT")
                    continue
                if opened_at is not None and settlement_time <= opened_at:
                    continue
                if closed_at is not None and settlement_time > closed_at:
                    continue
                await self._resolve_event(
                    report=report,
                    coverage_service=coverage_service,
                    plan=plan,
                    symbol=symbol,
                    settlement_time=settlement_time,
                    rate=_event_rate(event),
                    instruments=instruments,
                    existing_resolutions=existing_resolutions,
                    now=now,
                )

        # Durable recovery: rolling lookback only discovers recent lifecycles;
        # unresolved events older than the lookback are recovered from the
        # resolution table itself.
        if coverage_service is not None:
            try:
                await self._recover_unresolved(
                    report, coverage_service, instruments, now=now
                )
            except Exception as exc:
                report.errors.append(f"RECOVERY:{type(exc).__name__}")

        if self.trade_episodes is not None:
            try:
                await self.trade_episodes.materialize_pending_closed()
            except Exception as exc:
                report.errors.append(f"EPISODE_RECOVERY:{type(exc).__name__}")
        return report

    async def _resolution_status_map(self, coverage_service, symbol: str):
        resolutions = await coverage_service.event_resolutions(
            account_id=self.account_id,
            instrument_id=symbol,
            currency=self.currency,
        )
        return {
            resolution.settlement_timestamp: resolution.status
            for resolution in resolutions
        }

    async def _recover_unresolved(
        self, report, coverage_service, instruments, *, now: datetime
    ) -> None:
        queue = await coverage_service.retryable_unresolved()
        for resolution in queue:
            if resolution.account_id != self.account_id:
                continue
            if resolution.currency != self.currency:
                continue
            symbol = resolution.instrument_id
            settlement_time = _as_utc(resolution.settlement_timestamp)
            rate = resolution.funding_rate
            plan = None
            if self.trade_plans is not None:
                if resolution.trade_plan_id:
                    plan = await self.trade_plans.get(resolution.trade_plan_id)
                if plan is None and hasattr(self.trade_plans, "plan_covering"):
                    plan = await self.trade_plans.plan_covering(
                        symbol, settlement_time
                    )
            if rate is None:
                rate = await self._funding_rate_at(symbol, settlement_time)
            if rate is None:
                await coverage_service.record_event_resolution(
                    account_id=self.account_id,
                    instrument_id=symbol,
                    settlement_timestamp=settlement_time,
                    currency=self.currency,
                    status="UNPROVEN",
                    trade_plan_id=resolution.trade_plan_id,
                    reason="FUNDING_RATE_UNAVAILABLE",
                )
                report.skipped.append(f"{symbol}:FUNDING_RATE_UNAVAILABLE")
                continue
            existing = await self._resolution_status_map(coverage_service, symbol)
            await self._resolve_event(
                report=report,
                coverage_service=coverage_service,
                plan=plan,
                symbol=symbol,
                settlement_time=settlement_time,
                rate=rate,
                instruments=instruments,
                existing_resolutions=existing,
                recovery=True,
                now=now,
            )

    async def _funding_rate_at(
        self, symbol: str, settlement_time: datetime, max_pages: int = 5
    ) -> Decimal | None:
        """Exact fundingTime lookup using real OKX cursor semantics.

        OKX v5: before returns records NEWER than the requested ts; after
        returns records OLDER than the requested ts. Starting just above T and
        paging older with after=earliest keeps the requested instant reachable.
        """
        target_ms = int(settlement_time.timestamp() * 1000)
        cursor = target_ms + 1
        for _ in range(max(1, max_pages)):
            try:
                rows = await self.public_data.get_funding_rate_history(
                    symbol, before=None, after=str(cursor), limit=100
                )
            except Exception:
                return None
            if not rows:
                return None
            for row in rows:
                try:
                    if int(row["fundingTime"]) != target_ms:
                        continue
                    raw = row.get("realizedRate")
                    if raw in (None, ""):
                        return None
                    return D(raw)
                except (KeyError, TypeError, ValueError):
                    continue
            timestamps = [
                int(row["fundingTime"])
                for row in rows
                if isinstance(row.get("fundingTime"), (int, str))
            ]
            if not timestamps:
                return None
            previous = min(timestamps)
            if previous >= cursor:
                return None
            cursor = previous
        return None

    async def _resolve_event(
        self,
        *,
        report: FundingRunReport,
        coverage_service,
        plan,
        symbol: str,
        settlement_time: datetime,
        rate: Decimal,
        instruments: Mapping[str, Any],
        existing_resolutions: Mapping[datetime, str],
        recovery: bool = False,
        now: datetime | None = None,
    ) -> None:
        if existing_resolutions.get(settlement_time) in {"SETTLED", "NO_OP"}:
            return
        plan_id = getattr(plan, "trade_plan_id", None)
        if rate is None:
            await self._record_unresolved(
                coverage_service,
                symbol,
                settlement_time,
                None,
                plan_id,
                "FUNDING_RATE_UNAVAILABLE",
            )
            report.skipped.append(f"{symbol}:FUNDING_RATE_UNAVAILABLE")
            return
        if self.order_manager is None:
            await self._record_unresolved(
                coverage_service,
                symbol,
                settlement_time,
                rate,
                plan_id,
                "ORDER_MANAGER_UNAVAILABLE",
            )
            report.skipped.append(
                f"{symbol}:POSITION_QUANTITY_AT_SETTLEMENT_UNPROVEN"
            )
            return
        provenance = await self.order_manager.historical_quantity_at(
            account_id=self.account_id,
            symbol=symbol,
            at=settlement_time,
            currency=self.currency,
        )
        if provenance.status == HistoricalQuantityStatus.UNPROVEN:
            await self._record_unresolved(
                coverage_service,
                symbol,
                settlement_time,
                rate,
                plan_id,
                provenance.reason or "QUANTITY_UNPROVEN",
            )
            report.skipped.append(
                f"{symbol}:POSITION_QUANTITY_AT_SETTLEMENT_UNPROVEN"
            )
            return
        quantity = provenance.quantity or Decimal("0")
        if provenance.status == HistoricalQuantityStatus.PROVEN_ZERO:
            await coverage_service.record_event_resolution(
                account_id=self.account_id,
                instrument_id=symbol,
                settlement_timestamp=settlement_time,
                currency=self.currency,
                status="NO_OP",
                quantity=Decimal("0"),
                funding_rate=rate,
                trade_plan_id=plan_id,
                reason="QUANTITY_ZERO",
            )
            report.no_op += 1
            return
        if rate == 0 or quantity == 0:
            await coverage_service.record_event_resolution(
                account_id=self.account_id,
                instrument_id=symbol,
                settlement_timestamp=settlement_time,
                currency=self.currency,
                status="NO_OP",
                quantity=quantity,
                funding_rate=rate,
                trade_plan_id=plan_id,
                reason="ZERO_AMOUNT",
            )
            report.no_op += 1
            return
        spec = await self._contract_spec(symbol, plan, instruments)
        if spec.status.value != "PROVEN":
            await self._record_unresolved(
                coverage_service,
                symbol,
                settlement_time,
                rate,
                plan_id,
                f"INSTRUMENT_CONTRACT_SPEC_UNPROVEN:{spec.reason or 'UNPROVEN'}",
            )
            report.skipped.append(f"{symbol}:INSTRUMENT_CONTRACT_SPEC_UNPROVEN")
            return
        mark_price = await self._factual_settlement_mark(
            symbol, settlement_time, recovery=recovery, now=now
        )
        if mark_price is None:
            await coverage_service.record_event_resolution(
                account_id=self.account_id,
                instrument_id=symbol,
                settlement_timestamp=settlement_time,
                currency=self.currency,
                status="MARK_UNAVAILABLE",
                quantity=quantity,
                funding_rate=rate,
                trade_plan_id=plan_id,
                reason="NO_CLOSED_MARK_PRICE_CANDLE",
            )
            report.skipped.append(f"{symbol}:SETTLEMENT_MARK_UNAVAILABLE")
            return
        try:
            await self.settlement_service.settle(
                account_id=self.account_id,
                instrument_id=symbol,
                settlement_timestamp=settlement_time,
                signed_quantity=quantity,
                mark_price=mark_price,
                funding_rate=rate,
                contract_size=spec.contract_size,
                contract_multiplier=spec.contract_multiplier,
                currency=self.currency,
            )
        except Exception as exc:
            report.errors.append(f"{symbol}:{type(exc).__name__}")
            await self._record_unresolved(
                coverage_service,
                symbol,
                settlement_time,
                rate,
                plan_id,
                f"SETTLEMENT_FAILED:{type(exc).__name__}",
            )
            return
        transaction_id = None
        if self.ledger is not None:
            transaction_id = await self.ledger.transaction_id_for_event(
                _canonical_event_id(self.account_id, symbol, settlement_time)
            )
        await coverage_service.record_event_resolution(
            account_id=self.account_id,
            instrument_id=symbol,
            settlement_timestamp=settlement_time,
            currency=self.currency,
            status="SETTLED",
            quantity=quantity,
            mark_price=mark_price,
            funding_rate=rate,
            trade_plan_id=plan_id,
            ledger_transaction_id=transaction_id,
            reason=None,
        )
        report.settled += 1

    async def _record_unresolved(
        self,
        coverage_service,
        symbol: str,
        settlement_time: datetime,
        rate: Decimal | None,
        plan_id: str | None,
        reason: str,
    ) -> None:
        await coverage_service.record_event_resolution(
            account_id=self.account_id,
            instrument_id=symbol,
            settlement_timestamp=settlement_time,
            currency=self.currency,
            status="UNPROVEN",
            funding_rate=rate,
            trade_plan_id=plan_id,
            reason=reason[:120],
        )

    async def _contract_spec(self, symbol: str, plan, instruments) -> ContractSpecProvenance:
        spec = spec_from_instrument(symbol, instruments.get(symbol))
        if spec.proven:
            return spec
        if plan is None or self.order_manager is None:
            return spec
        order_id = getattr(plan, "order_id", None)
        if not order_id:
            return spec
        try:
            order = await self.order_manager.get(order_id)
        except Exception:
            return spec
        return spec_from_order_metadata(symbol, order)

    async def _factual_settlement_mark(
        self,
        symbol: str,
        settlement_time: datetime,
        *,
        recovery: bool = False,
        max_pages: int = 5,
        now: datetime | None = None,
    ) -> Decimal | None:
        """Return only OKX mark-price candle close proven at settlement.

        Rolling discovery uses the recent mark-candle endpoint. Durable
        unresolved recovery uses the historical endpoint and pages backward
        from the target instant instead of hoping the latest page reaches it.
        """
        target_ms = int(settlement_time.timestamp() * 1000)
        if not recovery:
            for bar, interval_ms, tolerance_ms in (
                ("1m", 60_000, 60_000),
                ("1H", 3_600_000, 3_600_000),
            ):
                try:
                    rows = await self.public_data.get_mark_price_candles(
                        symbol, bar=bar, limit=100
                    )
                except Exception:
                    continue
                best = _best_mark_candle(
                    rows, interval_ms=interval_ms, target_ms=target_ms
                )
                if best is None:
                    continue
                close_time_ms, close = best
                if target_ms - close_time_ms > tolerance_ms:
                    continue
                return close
            return None
        return await self._historical_mark_candle(
            symbol,
            settlement_time,
            max_pages=max_pages,
            now=now or datetime.now(UTC),
        )

    async def _historical_mark_candle(
        self,
        symbol: str,
        settlement_time: datetime,
        *,
        max_pages: int = 5,
        now: datetime | None = None,
    ) -> Decimal | None:
        target_ms = int(settlement_time.timestamp() * 1000)
        now = now or datetime.now(UTC)
        if now - settlement_time <= timedelta(minutes=100):
            bars = (("1m", 60_000, 60_000), ("1H", 3_600_000, 3_600_000))
        else:
            bars = (("1H", 3_600_000, 3_600_000),)
        # OKX v5 cursor semantics: before returns records NEWER than the
        # requested ts; after returns records OLDER than the requested ts.
        # Historical recovery therefore starts just above T and pages older
        # with after=earliest_open.
        for bar, interval_ms, tolerance_ms in bars:
            cursor = target_ms + interval_ms
            for _ in range(max(1, max_pages)):
                try:
                    rows = await self.public_data.get_history_mark_price_candles(
                        symbol,
                        bar=bar,
                        limit=100,
                        before=None,
                        after=str(cursor),
                    )
                except Exception:
                    break
                if not rows:
                    break
                best = _best_mark_candle(
                    rows, interval_ms=interval_ms, target_ms=target_ms
                )
                if best is not None:
                    close_time_ms, close = best
                    if target_ms - close_time_ms <= tolerance_ms:
                        return close
                earliest_open = min(
                    int(row[0])
                    for row in rows
                    if isinstance(row, list) and len(row) >= 6
                )
                if earliest_open >= cursor:
                    break
                cursor = earliest_open
        return None
def _best_mark_candle(
    rows, *, interval_ms: int, target_ms: int
) -> tuple[int, Decimal] | None:
    """Latest confirmed, positive mark candle already closed at target."""
    best: tuple[int, Decimal] | None = None
    for row in rows or []:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            open_time_ms = int(row[0])
            close = D(row[4])
            confirm = str(row[5])
        except (IndexError, TypeError, ValueError):
            continue
        if confirm != "1":
            continue
        if close <= 0:
            continue
        close_time_ms = open_time_ms + interval_ms
        if close_time_ms > target_ms:
            continue
        if best is None or close_time_ms > best[0]:
            best = (close_time_ms, close)
    return best


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


def _event_rate(event: dict) -> Decimal | None:
    """0 means PROVEN ZERO; None means rate provenance is unavailable."""
    raw = event.get("realizedRate")
    if raw in (None, ""):
        return None
    try:
        rate = D(raw)
    except Exception:
        return None
    return rate


def _canonical_event_id(
    account_id: str, instrument_id: str, settlement_time: datetime
) -> str:
    return (
        f"{account_id}|{instrument_id}|"
        f"{canonical_utc_timestamp_text(settlement_time)}"
    )
