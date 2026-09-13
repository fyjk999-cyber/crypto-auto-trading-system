"""Shadow candidate store: non-blocking enqueue, dedup and hard resource caps.

Failure policy is deliberately the INVERSE of the trading system's: every method
here is best-effort and swallows its own errors so a shadow problem can never
propagate into the realtime trading path. Callers get a falsy result, shadow work
is dropped, real trading continues.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from crypto_trader.shadow.models import (
    ACTIVE_STATUSES,
    STATUS_PENDING,
    ShadowCandidateORM,
    as_utc,
    utcnow,
)

#: §19 fixed first-version caps. Shadow is a SAMPLER, not a trade journal:
#: dropping samples is acceptable, slowing real trading is not.
MAX_ACTIVE_SHADOW_CANDIDATES = 100
MAX_ACTIVE_PER_SYMBOL = 5

#: §12 frozen rules. The first version uses one reproducible entry convention —
#: the next eligible closed bar — so no candidate can pick a favourable price.
ENTRY_RULE_NEXT_CLOSED_BAR = "NEXT_ELIGIBLE_CLOSED_BAR_OPEN"
EXIT_RULE_MAX_HOLD = "MAX_HOLD_SECONDS"
DEFAULT_MAX_HOLD_SECONDS = 3600
DEFAULT_HORIZONS = [300, 900, 3600]

#: §18 dedup: the same market view must not spawn a candidate every few seconds.
DEDUP_BUCKET_SECONDS = 300


def dedup_key_for(
    *,
    symbol: str,
    direction: str,
    strategy_version: str,
    regime: str,
    now: datetime,
    bucket_seconds: int = DEDUP_BUCKET_SECONDS,
) -> str:
    bucket = int(now.timestamp()) // max(1, bucket_seconds)
    raw = "|".join(
        (symbol.upper(), direction.upper(), strategy_version, regime.upper(), str(bucket))
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def rules_fingerprint(
    *,
    entry_rule: str,
    exit_rule: str,
    stop_rule: str | None,
    take_profit_rule: str | None,
    max_hold_seconds: int,
) -> str:
    raw = "|".join(
        (
            entry_rule,
            exit_rule,
            str(stop_rule),
            str(take_profit_rule),
            str(max_hold_seconds),
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


@dataclass(slots=True)
class ShadowEnqueueResult:
    accepted: bool
    reason: str
    candidate_id: str | None = None
    deduplicated: bool = False
    dropped: int = 0


class ShadowCandidateStore:
    """Durable, bounded, idempotent candidate persistence."""

    def __init__(
        self,
        session_factory,
        *,
        max_active: int = MAX_ACTIVE_SHADOW_CANDIDATES,
        max_per_symbol: int = MAX_ACTIVE_PER_SYMBOL,
        ttl_seconds: int = 6 * 3600,
    ) -> None:
        self.session_factory = session_factory
        self.max_active = max(1, int(max_active))
        self.max_per_symbol = max(1, int(max_per_symbol))
        self.ttl_seconds = max(60, int(ttl_seconds))
        #: Observability only (§33). Never consulted by trading code.
        self.dropped_total = 0
        self.error_count = 0

    # ------------------------------------------------------------------ enqueue
    async def enqueue(self, candidate: dict) -> ShadowEnqueueResult:
        """Best-effort, bounded insert. NEVER raises into the trading path."""
        try:
            return await self._enqueue(candidate)
        except Exception:
            # FAIL OPEN TOWARD REAL TRADING: record and drop.
            self.error_count += 1
            self.dropped_total += 1
            return ShadowEnqueueResult(False, "SHADOW_STORE_ERROR")

    async def _enqueue(self, candidate: dict) -> ShadowEnqueueResult:
        now = as_utc(candidate.get("created_at")) or utcnow()
        symbol = str(candidate["symbol"]).upper()
        direction = str(candidate["direction_hypothesis"])
        strategy_version = str(candidate.get("strategy_version") or "unknown")
        regime = str(candidate.get("market_regime") or "UNKNOWN")

        key = dedup_key_for(
            symbol=symbol,
            direction=direction,
            strategy_version=strategy_version,
            regime=regime,
            now=now,
        )

        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(ShadowCandidateORM).where(
                        ShadowCandidateORM.dedup_key == key
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                # §18: merge observations instead of exploding the row count.
                existing.observation_count = int(existing.observation_count or 1) + 1
                existing.updated_at = now
                await session.commit()
                return ShadowEnqueueResult(
                    True, "DEDUPLICATED", existing.candidate_id, deduplicated=True
                )

            active = (
                await session.execute(
                    select(func.count())
                    .select_from(ShadowCandidateORM)
                    .where(ShadowCandidateORM.status.in_(ACTIVE_STATUSES))
                )
            ).scalar_one()
            if int(active) >= self.max_active:
                self.dropped_total += 1
                return ShadowEnqueueResult(False, "SHADOW_SAMPLE_DROPPED_CAPACITY")

            per_symbol = (
                await session.execute(
                    select(func.count())
                    .select_from(ShadowCandidateORM)
                    .where(
                        ShadowCandidateORM.symbol == symbol,
                        ShadowCandidateORM.status.in_(ACTIVE_STATUSES),
                    )
                )
            ).scalar_one()
            if int(per_symbol) >= self.max_per_symbol:
                self.dropped_total += 1
                return ShadowEnqueueResult(False, "SHADOW_SAMPLE_DROPPED_PER_SYMBOL")

            candidate_id = str(candidate.get("candidate_id") or f"shadow_{key[:16]}")
            row = ShadowCandidateORM(
                candidate_id=candidate_id,
                created_at=now,
                updated_at=now,
                symbol=symbol,
                direction_hypothesis=direction,
                reference_price=str(candidate["reference_price"]),
                source_candidate_id=candidate.get("source_candidate_id"),
                source_decision_id=str(candidate["source_decision_id"]),
                strategy_id=str(candidate.get("strategy_id") or "unknown"),
                strategy_version=strategy_version,
                market_snapshot_id=candidate.get("market_snapshot_id"),
                factor_snapshot_id=candidate.get("factor_snapshot_id"),
                market_regime=regime,
                chieftrader_action=str(candidate.get("chieftrader_action") or ""),
                chieftrader_reason=str(candidate.get("chieftrader_reason") or "")[:2000],
                hypothetical_entry_rule=str(
                    candidate.get("hypothetical_entry_rule") or ENTRY_RULE_NEXT_CLOSED_BAR
                ),
                hypothetical_exit_rule=str(
                    candidate.get("hypothetical_exit_rule") or EXIT_RULE_MAX_HOLD
                ),
                stop_rule=candidate.get("stop_rule"),
                take_profit_rule=candidate.get("take_profit_rule"),
                max_hold_seconds=int(
                    candidate.get("max_hold_seconds") or DEFAULT_MAX_HOLD_SECONDS
                ),
                evaluation_horizons_json=list(
                    candidate.get("evaluation_horizons") or DEFAULT_HORIZONS
                ),
                rules_fingerprint=rules_fingerprint(
                    entry_rule=str(
                        candidate.get("hypothetical_entry_rule")
                        or ENTRY_RULE_NEXT_CLOSED_BAR
                    ),
                    exit_rule=str(
                        candidate.get("hypothetical_exit_rule") or EXIT_RULE_MAX_HOLD
                    ),
                    stop_rule=candidate.get("stop_rule"),
                    take_profit_rule=candidate.get("take_profit_rule"),
                    max_hold_seconds=int(
                        candidate.get("max_hold_seconds") or DEFAULT_MAX_HOLD_SECONDS
                    ),
                ),
                dedup_key=key,
                status=STATUS_PENDING,
                observation_count=1,
                expires_at=now + timedelta(seconds=self.ttl_seconds),
            )
            session.add(row)
            await session.commit()
            return ShadowEnqueueResult(True, "CREATED", candidate_id)

    # -------------------------------------------------------------------- read
    async def get(self, candidate_id: str) -> ShadowCandidateORM | None:
        async with self.session_factory() as session:
            return await session.get(ShadowCandidateORM, candidate_id)

    async def list_active(self, *, limit: int = 200) -> list[ShadowCandidateORM]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(ShadowCandidateORM)
                    .where(ShadowCandidateORM.status.in_(ACTIVE_STATUSES))
                    .order_by(
                        ShadowCandidateORM.created_at, ShadowCandidateORM.candidate_id
                    )
                    .limit(max(1, limit))
                )
            ).scalars().all()
            return list(rows)

    async def counts(self) -> dict:
        """Observability snapshot; isolated from trading health (§33)."""
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(ShadowCandidateORM.status, func.count())
                    .group_by(ShadowCandidateORM.status)
                )
            ).all()
        by_status = {str(status): int(count) for status, count in rows}
        return {
            "by_status": by_status,
            "active": sum(by_status.get(s, 0) for s in ACTIVE_STATUSES),
            "dropped_total": self.dropped_total,
            "error_count": self.error_count,
        }

    async def immutable_fingerprint(self, candidate_id: str) -> str | None:
        row = await self.get(candidate_id)
        return None if row is None else str(row.rules_fingerprint)


def reference_price_decimal(candidate: ShadowCandidateORM) -> Decimal:
    return Decimal(str(candidate.reference_price))


__all__ = [
    "DEDUP_BUCKET_SECONDS",
    "DEFAULT_HORIZONS",
    "DEFAULT_MAX_HOLD_SECONDS",
    "ENTRY_RULE_NEXT_CLOSED_BAR",
    "EXIT_RULE_MAX_HOLD",
    "MAX_ACTIVE_PER_SYMBOL",
    "MAX_ACTIVE_SHADOW_CANDIDATES",
    "ShadowCandidateStore",
    "ShadowEnqueueResult",
    "dedup_key_for",
    "reference_price_decimal",
    "rules_fingerprint",
]
