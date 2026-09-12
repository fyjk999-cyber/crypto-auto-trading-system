"""Shadow persistence: its own namespace, never the factual trading tables.

These rows describe HYPOTHETICAL trades. They must never be mistaken for real
activity, so they live in ``shadow_*`` tables, carry ``factual = False`` and
``evidence_type = SHADOW_EPISODE``, and are excluded from every real consumer
(orders, fills, positions, accounting, capacity, Growth's factual path).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from crypto_trader.persistence.models import Base

STATUS_PENDING = "PENDING"
STATUS_TRACKING = "TRACKING"
STATUS_MATURED = "MATURED"
STATUS_EVALUATED = "EVALUATED"
STATUS_EXPIRED = "EXPIRED"
STATUS_INVALIDATED = "INVALIDATED"

#: Stages that still occupy an "active" slot against the resource caps.
ACTIVE_STATUSES = (STATUS_PENDING, STATUS_TRACKING, STATUS_MATURED)

OUTCOME_MISSED_OPPORTUNITY = "MISSED_OPPORTUNITY"
OUTCOME_CORRECT_NO_TRADE = "CORRECT_NO_TRADE"
OUTCOME_AMBIGUOUS = "AMBIGUOUS"
OUTCOME_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

EVIDENCE_TYPE_SHADOW_EPISODE = "SHADOW_EPISODE"
EVALUATOR_VERSION = "shadow-eval-v1"


class ShadowCandidateORM(Base):
    """A frozen counterfactual: the rules may never change after creation."""

    __tablename__ = "shadow_candidates"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_shadow_candidates_dedup_key"),
    )

    candidate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    direction_hypothesis: Mapped[str] = mapped_column(String(8), nullable=False)
    reference_price: Mapped[str] = mapped_column(String(80), nullable=False)

    source_candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_decision_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)

    market_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    factor_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    market_regime: Mapped[str] = mapped_column(String(64), nullable=False)
    chieftrader_action: Mapped[str] = mapped_column(String(32), nullable=False)
    chieftrader_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Immutable rule set (frozen at creation; see §12 no-look-ahead).
    hypothetical_entry_rule: Mapped[str] = mapped_column(String(64), nullable=False)
    hypothetical_exit_rule: Mapped[str] = mapped_column(String(64), nullable=False)
    stop_rule: Mapped[str | None] = mapped_column(String(80), nullable=True)
    take_profit_rule: Mapped[str | None] = mapped_column(String(80), nullable=True)
    max_hold_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

    evaluation_horizons_json: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
    rules_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_PENDING, index=True
    )
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class ShadowEpisodeORM(Base):
    """Deterministic evaluation of a matured shadow candidate."""

    __tablename__ = "shadow_episodes"
    __table_args__ = (
        UniqueConstraint("shadow_candidate_id", name="uq_shadow_episodes_candidate"),
    )

    shadow_episode_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    shadow_candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_decision_id: Mapped[str] = mapped_column(String(64), nullable=False)

    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    regime: Mapped[str] = mapped_column(String(64), nullable=False)

    hypothetical_entry_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    hypothetical_entry_price: Mapped[str] = mapped_column(String(80), nullable=False)
    hypothetical_exit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hypothetical_exit_price: Mapped[str | None] = mapped_column(String(80), nullable=True)

    normalized_notional: Mapped[str] = mapped_column(String(80), nullable=False)
    gross_return: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fee_adjusted_return: Mapped[str | None] = mapped_column(String(80), nullable=True)
    mfe: Mapped[str | None] = mapped_column(String(80), nullable=True)
    mae: Mapped[str | None] = mapped_column(String(80), nullable=True)

    holding_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome_class: Mapped[str] = mapped_column(String(32), nullable=False)

    # Non-negotiable markers: this is evidence, not a trade.
    factual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EVIDENCE_TYPE_SHADOW_EPISODE
    )
    evaluator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ShadowEvaluationRunORM(Base):
    """One pass of the evaluator: observability without touching trading health."""

    __tablename__ = "shadow_evaluation_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matured: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dropped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = [
    "ACTIVE_STATUSES",
    "EVALUATOR_VERSION",
    "EVIDENCE_TYPE_SHADOW_EPISODE",
    "OUTCOME_AMBIGUOUS",
    "OUTCOME_CORRECT_NO_TRADE",
    "OUTCOME_INSUFFICIENT_DATA",
    "OUTCOME_MISSED_OPPORTUNITY",
    "STATUS_EVALUATED",
    "STATUS_EXPIRED",
    "STATUS_INVALIDATED",
    "STATUS_MATURED",
    "STATUS_PENDING",
    "STATUS_TRACKING",
    "ShadowCandidateORM",
    "ShadowEpisodeORM",
    "ShadowEvaluationRunORM",
    "as_utc",
    "utcnow",
]
