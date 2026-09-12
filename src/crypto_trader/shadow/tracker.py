"""Shadow tracker + deterministic evaluator (PHASE B and C).

The tracker advances a candidate through PENDING -> TRACKING -> MATURED using
FUTURE FACTUAL market observations only. The evaluator turns a matured candidate
into a deterministic ShadowEpisode.

Both are pure w.r.t. trading: they read market observations and shadow rows, and
write only shadow rows. No order, fill, position, balance or ledger write exists
in this module, and no provider/LLM call is made anywhere. Missing future data
produces INSUFFICIENT_DATA / INVALIDATED — never a fabricated result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.shadow.candidate_store import ShadowCandidateStore
from crypto_trader.shadow.models import (
    EVALUATOR_VERSION,
    EVIDENCE_TYPE_SHADOW_EPISODE,
    OUTCOME_AMBIGUOUS,
    OUTCOME_CORRECT_NO_TRADE,
    OUTCOME_MISSED_OPPORTUNITY,
    STATUS_EVALUATED,
    STATUS_INVALIDATED,
    STATUS_MATURED,
    STATUS_PENDING,
    STATUS_TRACKING,
    ShadowCandidateORM,
    ShadowEpisodeORM,
    ShadowEvaluationRunORM,
    as_utc,
    utcnow,
)

#: §15 normalized size. Comparisons are between strategies, not account P&L.
NORMALIZED_NOTIONAL = Decimal("100")

#: Deterministic outcome threshold. A counterfactual is only a MISSED
#: OPPORTUNITY when it cleared both a return threshold AND an adverse-excursion
#: bound; anything in between is AMBIGUOUS rather than a lesson.
MISSED_RETURN_THRESHOLD = Decimal("0.002")
MAX_ACCEPTABLE_MAE = Decimal("0.01")

#: Deterministic fee model for the hypothetical round trip.
SHADOW_FEE_RATE = Decimal("0.001")


@dataclass(slots=True)
class MarketObservation:
    """A factual observation the runtime ALREADY produced (read-only reuse)."""

    symbol: str
    observed_at: datetime
    price: Decimal
    bar_open: Decimal | None = None


@dataclass(slots=True)
class ShadowRunReport:
    considered: int = 0
    matured: int = 0
    evaluated: int = 0
    invalidated: int = 0
    dropped: int = 0
    errors: int = 0
    error_summary: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "considered": self.considered,
            "matured": self.matured,
            "evaluated": self.evaluated,
            "invalidated": self.invalidated,
            "dropped": self.dropped,
            "errors": self.errors,
            "error_summary": self.error_summary[:5],
        }


class CounterfactualOutcomeEvaluator:
    """Deterministic hypothetical P&L for ONE candidate. No LLM ever computes a
    return (§14).

    Distinct from ``shadow.evaluation.ShadowEvaluator``, which aggregates
    portfolio-style metrics (Sharpe/Sortino/profit factor) across many closed
    virtual positions. That aggregator can consume the episodes produced here;
    the two are layers, not alternatives, hence the explicit name.
    """

    def evaluate(
        self,
        *,
        candidate: ShadowCandidateORM,
        entry_at: datetime,
        entry_price: Decimal,
        exit_at: datetime,
        exit_price: Decimal,
        mfe: Decimal,
        mae: Decimal,
        exit_reason: str,
    ) -> dict:
        direction = str(candidate.direction_hypothesis).upper()
        sign = Decimal("-1") if direction == "SHORT" else Decimal("1")
        if direction == "NONE":
            # A directionless abstention is observable but not scorable: it must
            # not be silently scored as a long.
            return {
                "outcome_class": OUTCOME_AMBIGUOUS,
                "gross_return": None,
                "fee_adjusted_return": None,
                "mfe": str(mfe),
                "mae": str(mae),
                "exit_reason": exit_reason,
            }

        price_delta = (Decimal(exit_price) - Decimal(entry_price)) * sign
        gross_return = price_delta / Decimal(entry_price)
        fees = SHADOW_FEE_RATE * 2
        fee_adjusted = gross_return - fees

        if fee_adjusted >= MISSED_RETURN_THRESHOLD and mae <= MAX_ACCEPTABLE_MAE:
            outcome = OUTCOME_MISSED_OPPORTUNITY
        elif fee_adjusted <= Decimal("0"):
            outcome = OUTCOME_CORRECT_NO_TRADE
        else:
            outcome = OUTCOME_AMBIGUOUS

        return {
            "outcome_class": outcome,
            "gross_return": str(gross_return),
            "fee_adjusted_return": str(fee_adjusted),
            "mfe": str(mfe),
            "mae": str(mae),
            "exit_reason": exit_reason,
            "entry_at": entry_at,
            "exit_at": exit_at,
            "entry_price": str(entry_price),
            "exit_price": str(exit_price),
        }


class ShadowTracker:
    """Advances candidates on future factual observations, then evaluates them."""

    def __init__(
        self,
        session_factory,
        *,
        candidate_store: ShadowCandidateStore | None = None,
        evaluator: CounterfactualOutcomeEvaluator | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.candidates = candidate_store or ShadowCandidateStore(session_factory)
        self.evaluator = evaluator or CounterfactualOutcomeEvaluator()
        self.last_run_at: datetime | None = None
        self.last_evaluation_at: datetime | None = None
        self.error_count = 0

    async def run_once(
        self,
        *,
        observations: list[MarketObservation],
        now: datetime | None = None,
        limit: int = 200,
    ) -> ShadowRunReport:
        """One bounded pass. NEVER raises: shadow failure must not stop trading."""
        report = ShadowRunReport()
        now = as_utc(now) or utcnow()
        self.last_run_at = now
        try:
            await self._run(report, observations=observations, now=now, limit=limit)
        except Exception as exc:  # noqa: BLE001 - deliberate fail-open
            self.error_count += 1
            report.errors += 1
            report.error_summary.append(f"{type(exc).__name__}")
        return report

    async def _run(
        self,
        report: ShadowRunReport,
        *,
        observations: list[MarketObservation],
        now: datetime,
        limit: int,
    ) -> None:
        by_symbol: dict[str, list[MarketObservation]] = {}
        for obs in observations:
            by_symbol.setdefault(obs.symbol.upper(), []).append(obs)

        run = ShadowEvaluationRunORM(
            run_id=f"shadow_run_{int(now.timestamp() * 1000)}",
            started_at=now,
            considered=0,
            evaluated=0,
            matured=0,
            dropped=0,
            errors=0,
        )

        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    _active_candidates_query(limit)
                )
            ).scalars().all()

            for candidate in rows:
                report.considered += 1
                obs_list = sorted(
                    by_symbol.get(candidate.symbol.upper(), []),
                    key=lambda o: o.observed_at,
                )
                decision = _advance(candidate, obs_list=obs_list, now=now)
                if decision is None:
                    continue
                status, payload = decision
                if status == STATUS_MATURED:
                    report.matured += 1
                elif status == STATUS_INVALIDATED:
                    report.invalidated += 1
                candidate.status = status
                candidate.updated_at = now
                if payload is not None:
                    episode = self._build_episode(
                        candidate=candidate, payload=payload, now=now
                    )
                    if episode is not None:
                        session.add(episode)
                        report.evaluated += 1
                        candidate.status = STATUS_EVALUATED
                        self.last_evaluation_at = now
            session.add(run)
            run.considered = report.considered
            run.matured = report.matured
            run.evaluated = report.evaluated
            run.dropped = report.dropped
            run.errors = report.errors
            run.finished_at = utcnow()
            await session.commit()

    def _build_episode(
        self, *, candidate: ShadowCandidateORM, payload: dict, now: datetime
    ) -> ShadowEpisodeORM | None:
        result = self.evaluator.evaluate(
            candidate=candidate,
            entry_at=payload["entry_at"],
            entry_price=payload["entry_price"],
            exit_at=payload["exit_at"],
            exit_price=payload["exit_price"],
            mfe=payload["mfe"],
            mae=payload["mae"],
            exit_reason=payload["exit_reason"],
        )
        holding = int(
            max(
                0,
                (
                    payload["exit_at"] - payload["entry_at"]
                ).total_seconds(),
            )
        )
        return ShadowEpisodeORM(
            shadow_episode_id=f"shadow_ep_{candidate.candidate_id}"[:64],
            shadow_candidate_id=candidate.candidate_id,
            source_decision_id=candidate.source_decision_id,
            symbol=candidate.symbol,
            direction=candidate.direction_hypothesis,
            strategy_id=candidate.strategy_id,
            strategy_version=candidate.strategy_version,
            regime=candidate.market_regime,
            hypothetical_entry_at=payload["entry_at"],
            hypothetical_entry_price=str(payload["entry_price"]),
            hypothetical_exit_at=payload["exit_at"],
            hypothetical_exit_price=str(payload["exit_price"]),
            normalized_notional=str(NORMALIZED_NOTIONAL),
            gross_return=result["gross_return"],
            fee_adjusted_return=result["fee_adjusted_return"],
            mfe=str(result["mfe"]),
            mae=str(result["mae"]),
            holding_seconds=holding,
            exit_reason=result["exit_reason"],
            outcome_class=result["outcome_class"],
            factual=False,
            evidence_type=EVIDENCE_TYPE_SHADOW_EPISODE,
            evaluator_version=EVALUATOR_VERSION,
            created_at=now,
        )


def _active_candidates_query(limit: int):
    return (
        select(ShadowCandidateORM)
        .where(ShadowCandidateORM.status.in_((STATUS_PENDING, STATUS_TRACKING)))
        .order_by(ShadowCandidateORM.created_at, ShadowCandidateORM.candidate_id)
        .limit(max(1, limit))
    )


def _advance(
    candidate: ShadowCandidateORM,
    *,
    obs_list: list[MarketObservation],
    now: datetime,
) -> tuple[str, dict | None] | None:
    """Pure state machine over future factual observations.

    Returns ``None`` (no change) when the candidate has not yet matured, or a
    ``(status, payload)`` pair. Missing data never fabricates: it yields
    INVALIDATED at deadline, not a synthetic episode.
    """
    created = as_utc(candidate.created_at)
    expires = as_utc(candidate.expires_at)
    if created is None:
        return None

    # Future observations only: no look-ahead, no retro-fitting (§12).
    future = [o for o in obs_list if o.observed_at > created]
    if not future:
        if expires is not None and now >= expires:
            return STATUS_INVALIDATED, None
        return None

    entry_obs = future[0]
    entry_at = entry_obs.observed_at
    entry_price = Decimal(entry_obs.bar_open or entry_obs.price)

    horizon_end = entry_at + timedelta(seconds=max(1, int(candidate.max_hold_seconds)))
    window = [o for o in future if entry_at <= o.observed_at <= horizon_end]

    if now < horizon_end and not window:
        return STATUS_TRACKING, None
    if now < horizon_end:
        return STATUS_TRACKING, None

    exit_obs = window[-1] if window else entry_obs
    prices = [Decimal(o.price) for o in window] or [entry_price]
    sign = Decimal("-1") if candidate.direction_hypothesis == "SHORT" else Decimal("1")
    favourable = max((p - entry_price) * sign for p in prices)
    adverse = min((p - entry_price) * sign for p in prices)
    mfe = favourable / entry_price
    mae = (-adverse / entry_price) if adverse < 0 else Decimal("0")

    if candidate.direction_hypothesis not in ("LONG", "SHORT"):
        # Directionless sample: recorded for coverage, not scored.
        return STATUS_EVALUATED, {
            "entry_at": entry_at,
            "entry_price": entry_price,
            "exit_at": exit_obs.observed_at,
            "exit_price": Decimal(exit_obs.price),
            "mfe": mfe,
            "mae": mae,
            "exit_reason": "DIRECTIONLESS_UNSCORED",
        }

    return STATUS_MATURED, {
        "entry_at": entry_at,
        "entry_price": entry_price,
        "exit_at": exit_obs.observed_at,
        "exit_price": Decimal(exit_obs.price),
        "mfe": mfe,
        "mae": mae,
        "exit_reason": "MAX_HOLD_ELAPSED",
    }


__all__ = [
    "MISSED_RETURN_THRESHOLD",
    "MAX_ACCEPTABLE_MAE",
    "NORMALIZED_NOTIONAL",
    "SHADOW_FEE_RATE",
    "MarketObservation",
    "CounterfactualOutcomeEvaluator",
    "ShadowRunReport",
    "ShadowTracker",
]
