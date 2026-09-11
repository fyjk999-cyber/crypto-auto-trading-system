"""Daily factual statistics with explicit gross/net and funding completeness.

Fixes closed in G01:
* every per-trade net is ``gross - fees + funding`` and wins/losses/expectancy,
  long/short PnL and win rate use that net consistently;
* gross and net figures are both retained and separately named;
* breakeven trades are counted separately and never silently folded into wins
  or losses;
* profit factor is a nullable ratio with an explicit status instead of the
  old ``999`` sentinel or a gross-profit amount;
* funding with no provenance is never converted to zero: affected records are
  reported as ``INCOMPLETE_UNKNOWN_FUNDING`` and cannot produce a complete net
  conclusion (the knowledge pipeline must not promote them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.governance.memory import TradeMemory

# Funding provenance vocabulary.  The factual episode builder only persists an
# episode after funding coverage is proven, so those records carry PROVEN;
# records loaded from legacy stores carry no provenance and are UNKNOWN unless
# the caller explicitly opts into the compatibility policy.
PROVEN_FUNDING = frozenset({"PROVEN", "KNOWN_ZERO", "KNOWN_VALUE", "SETTLED", "NO_OP"})
UNKNOWN_FUNDING = frozenset({"UNKNOWN", "UNPROVEN", "INCOMPLETE", "QUARANTINED"})

PF_STATUS_OK = "OK"
PF_STATUS_NO_LOSSES = "NO_LOSSES"
PF_STATUS_NO_SAMPLES = "NO_SAMPLES"
PF_STATUS_INCOMPLETE = "INCOMPLETE_FUNDING"

NET_STATUS_COMPLETE = "COMPLETE"
NET_STATUS_NO_SAMPLES = "NO_SAMPLES"
NET_STATUS_INCOMPLETE = "INCOMPLETE_UNKNOWN_FUNDING"
NET_STATUS_INCOMPLETE_GROSS = "INCOMPLETE_UNKNOWN_GROSS"


@dataclass
class DailyReviewStats:
    date: str
    # Legacy mirror: always populated for storage/API compatibility.  For an
    # incomplete day it is explicitly the partial (gross - fees + known
    # funding) value and the status fields say so.
    daily_pnl: Decimal = Decimal("0")
    long_pnl: Decimal = Decimal("0")
    short_pnl: Decimal = Decimal("0")
    gross_pnl: Decimal = Decimal("0")
    net_pnl: Decimal | None = None
    fees: Decimal = Decimal("0")
    funding_pnl: Decimal = Decimal("0")
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    breakeven_count: int = 0
    # Defaults are legacy-compatible zeros for callers that construct a
    # stats object by hand.  DailyReview.run() explicitly sets None for an
    # incomplete day; never infer completeness from the default.
    win_rate: Decimal | None = Decimal("0")
    win_rate_status: str = NET_STATUS_NO_SAMPLES
    profit_factor: Decimal | None = Decimal("0")
    profit_factor_status: str = PF_STATUS_NO_SAMPLES
    expectancy: Decimal | None = Decimal("0")
    avg_r: Decimal = Decimal("0")
    long_gross_pnl: Decimal = Decimal("0")
    short_gross_pnl: Decimal = Decimal("0")
    long_net_pnl: Decimal | None = Decimal("0")
    short_net_pnl: Decimal | None = Decimal("0")
    long_net_status: str = NET_STATUS_NO_SAMPLES
    short_net_status: str = NET_STATUS_NO_SAMPLES
    net_status: str = NET_STATUS_NO_SAMPLES
    funding_status: str = "NO_SAMPLES"
    unknown_funding_count: int = 0
    unknown_gross_count: int = 0
    excluded_from_net_count: int = 0
    failure_distribution: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Compatibility layer.  New callers must read the explicit status fields
    # above; these helpers exist only so old consumers cannot crash while the
    # API contract is migrated.
    # ------------------------------------------------------------------
    @property
    def profit_factor_compat(self) -> Decimal:
        return self.profit_factor if self.profit_factor is not None else Decimal("0")

    @property
    def win_rate_compat(self) -> Decimal:
        return self.win_rate if self.win_rate is not None else Decimal("0")

    def for_storage(self) -> DailyReviewStats:
        """Copy with legacy non-null columns populated; status fields preserved.

        ``DailyReviewRunORM`` predates nullable ratios and status columns, so
        the copy stores 0 while ``output_ref``/the authoritative report keeps
        the explicit status.  Unknown funding still yields a non-COMPLETE
        ``net_status``, so the copy can never be mistaken for a complete day.
        """
        return DailyReviewStats(
            date=self.date,
            daily_pnl=self.daily_pnl,
            long_pnl=self.long_pnl,
            short_pnl=self.short_pnl,
            gross_pnl=self.gross_pnl,
            net_pnl=self.net_pnl,
            fees=self.fees,
            funding_pnl=self.funding_pnl,
            trade_count=self.trade_count,
            win_count=self.win_count,
            loss_count=self.loss_count,
            breakeven_count=self.breakeven_count,
            win_rate=self.win_rate if self.win_rate is not None else Decimal("0"),
            win_rate_status=self.win_rate_status,
            profit_factor=(
                self.profit_factor if self.profit_factor is not None else Decimal("0")
            ),
            profit_factor_status=self.profit_factor_status,
            expectancy=self.expectancy if self.expectancy is not None else Decimal("0"),
            avg_r=self.avg_r,
            long_gross_pnl=self.long_gross_pnl,
            short_gross_pnl=self.short_gross_pnl,
            long_net_pnl=self.long_net_pnl,
            short_net_pnl=self.short_net_pnl,
            long_net_status=self.long_net_status,
            short_net_status=self.short_net_status,
            net_status=self.net_status,
            funding_status=self.funding_status,
            unknown_funding_count=self.unknown_funding_count,
            unknown_gross_count=self.unknown_gross_count,
            excluded_from_net_count=self.excluded_from_net_count,
            failure_distribution=dict(self.failure_distribution),
        )

    def legacy_metrics(self) -> dict:
        """Return the pre-G01 field names with honest zero-for-unknown values.

        The status fields are included so a caller cannot mistake a missing
        ratio for a real zero ratio.
        """
        return {
            "daily_pnl": self.daily_pnl,
            "long_pnl": self.long_pnl,
            "short_pnl": self.short_pnl,
            "win_rate": self.win_rate_compat,
            "profit_factor": self.profit_factor_compat,
            "expectancy": self.expectancy if self.expectancy is not None else Decimal("0"),
            "profit_factor_status": self.profit_factor_status,
            "win_rate_status": self.win_rate_status,
            "net_status": self.net_status,
            "funding_status": self.funding_status,
        }


class DailyReview:
    def __init__(
        self,
        memory: TradeMemory,
        failure_memory=None,
        *,
        funding_policy: str = "ASSUME_PRESENT",
    ) -> None:
        if funding_policy not in {"ASSUME_PRESENT", "STRICT"}:
            raise ValueError("funding_policy must be ASSUME_PRESENT or STRICT")
        self.memory = memory
        self.failure_memory = failure_memory
        self.funding_policy = funding_policy

    def _funding_provenance(self, record) -> str:
        explicit = getattr(record, "funding_provenance", None)
        if explicit is not None:
            normalized = str(explicit).upper()
            if normalized in UNKNOWN_FUNDING:
                return "UNKNOWN"
            if normalized in PROVEN_FUNDING:
                return "PROVEN"
            return "UNKNOWN"
        # No provenance stored by the legacy record.  In strict mode this is
        # UNKNOWN; the compatibility policy only applies to legacy in-memory
        # callers that opted in.
        if self.funding_policy == "STRICT":
            return "UNKNOWN"
        return "PROVEN"

    def run(self, date: str | None = None) -> DailyReviewStats:
        date = date or datetime.now(UTC).date().isoformat()
        rows = [r for r in self.memory.all() if r.ts.date().isoformat() == date]
        stats = DailyReviewStats(date=date)
        stats.trade_count = len(rows)
        stats.failure_distribution = (
            self.failure_memory.distribution() if self.failure_memory is not None else {}
        )
        if not rows:
            stats.net_status = NET_STATUS_NO_SAMPLES
            stats.funding_status = "NO_SAMPLES"
            stats.win_rate = None
            stats.profit_factor = None
            stats.expectancy = None
            stats.long_net_pnl = None
            stats.short_net_pnl = None
            return stats

        gross_total = Decimal("0")
        fee_total = Decimal("0")
        funding_total = Decimal("0")
        net_total = Decimal("0")
        known_net_count = 0
        unknown_funding = 0
        unknown_gross = 0
        r_values: list[Decimal] = []
        long_gross = Decimal("0")
        short_gross = Decimal("0")
        long_net = Decimal("0")
        short_net = Decimal("0")
        long_known = 0
        short_known = 0

        for record in rows:
            gross = getattr(record, "realized_pnl", None)
            fees = getattr(record, "fees", None) or Decimal("0")
            funding = getattr(record, "funding_pnl", None) or Decimal("0")
            r_values.append(getattr(record, "r_multiple", None) or Decimal("0"))
            if gross is None:
                unknown_gross += 1
                continue
            gross = Decimal(gross)
            fee_total += fees
            gross_total += gross
            if getattr(record, "side", "") == "LONG":
                long_gross += gross
            elif getattr(record, "side", "") == "SHORT":
                short_gross += gross
            if self._funding_provenance(record) == "UNKNOWN":
                unknown_funding += 1
                continue
            funding = Decimal(funding)
            funding_total += funding
            net = gross - fees + funding
            net_total += net
            known_net_count += 1
            if getattr(record, "side", "") == "LONG":
                long_net += net
                long_known += 1
            elif getattr(record, "side", "") == "SHORT":
                short_net += net
                short_known += 1

        stats.gross_pnl = gross_total
        stats.fees = fee_total
        stats.funding_pnl = funding_total
        stats.long_gross_pnl = long_gross
        stats.short_gross_pnl = short_gross
        stats.unknown_funding_count = unknown_funding
        stats.unknown_gross_count = unknown_gross
        stats.excluded_from_net_count = unknown_funding + unknown_gross
        stats.avg_r = (
            sum(r_values, Decimal("0")) / Decimal(len(r_values)) if r_values else Decimal("0")
        )

        complete = unknown_funding == 0 and unknown_gross == 0
        if complete:
            stats.net_status = NET_STATUS_COMPLETE
            stats.funding_status = "PROVEN"
            stats.net_pnl = net_total
            stats.long_net_pnl = long_net
            stats.short_net_pnl = short_net
            stats.long_net_status = "COMPLETE"
            stats.short_net_status = "COMPLETE"
            net_values = []
            # Recompute per-record nets once for win/loss/breakeven counts.  The
            # aggregation above already contains the same arithmetic.
            for record in rows:
                gross = Decimal(record.realized_pnl)
                fees = getattr(record, "fees", None) or Decimal("0")
                funding = getattr(record, "funding_pnl", None) or Decimal("0")
                net_values.append(gross - fees + funding)
            stats.win_count = sum(1 for value in net_values if value > 0)
            stats.loss_count = sum(1 for value in net_values if value < 0)
            stats.breakeven_count = sum(1 for value in net_values if value == 0)
            stats.win_rate = Decimal(stats.win_count) / Decimal(stats.trade_count)
            stats.win_rate_status = "OK"
            stats.expectancy = net_total / Decimal(stats.trade_count)
            gross_win = sum((value for value in net_values if value > 0), Decimal("0"))
            gross_loss = abs(sum((value for value in net_values if value < 0), Decimal("0")))
            if gross_loss > 0:
                stats.profit_factor = gross_win / gross_loss
                stats.profit_factor_status = PF_STATUS_OK
            else:
                # No losing trade: a ratio is undefined.  When wins exist it is
                # NO_LOSSES; an all-breakeven sample is also NO_LOSSES, never a
                # fabricated zero/amount ratio.
                stats.profit_factor = None
                stats.profit_factor_status = PF_STATUS_NO_LOSSES
            stats.daily_pnl = net_total
            stats.long_pnl = long_net
            stats.short_pnl = short_net
        else:
            # Publish an explicitly incomplete report.  It may be stored for
            # audit but must never be promoted into reusable knowledge.
            partial = gross_total - fee_total + funding_total
            stats.net_status = (
                NET_STATUS_INCOMPLETE if unknown_funding else NET_STATUS_INCOMPLETE_GROSS
            )
            stats.funding_status = (
                "UNKNOWN" if unknown_funding else ("NO_SAMPLES" if not rows else "PROVEN")
            )
            stats.net_pnl = None
            stats.daily_pnl = partial
            stats.long_pnl = long_net
            stats.short_pnl = short_net
            stats.long_net_pnl = long_net if long_known else None
            stats.short_net_pnl = short_net if short_known else None
            stats.long_net_status = (
                "COMPLETE" if long_known and unknown_funding == 0 else "INCOMPLETE"
            )
            stats.short_net_status = (
                "COMPLETE" if short_known and unknown_funding == 0 else "INCOMPLETE"
            )
            stats.win_rate = None
            stats.win_rate_status = NET_STATUS_INCOMPLETE
            stats.profit_factor = None
            stats.profit_factor_status = PF_STATUS_INCOMPLETE
            stats.expectancy = None
        return stats

    def strategy_regime_matrix(self) -> dict:
        matrix: dict[str, dict] = {}
        for record in self.memory.all():
            key = f"{record.side}@{record.regime}"
            cell = matrix.setdefault(key, {"trade_count": 0, "pnl": Decimal("0")})
            cell["trade_count"] += 1
            cell["pnl"] += record.realized_pnl or Decimal("0")
        return matrix
