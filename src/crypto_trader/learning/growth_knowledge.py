"""G04: evidence-graded lessons, patterns, profiles and conditional compression.

Promotion rules (never profitability-based)
-------------------------------------------
* A lesson from one episode is a **candidate** with ``sample_count=1``.
* A pattern is only ``VALIDATED`` with at least ``min_pattern_samples``
  independent distinct episodes and zero contrary episodes.  Contrary
  episodes produce ``CONTESTED`` with an explicit grade instead of silently
  increasing confidence.
* ``sample_count`` counts distinct episode ids; republishing the same episode
  never increases it.
* A net-positive episode does not by itself support a thesis: pattern support
  is derived from the structured review's evidence references (support vs
  contrary), not from PnL.
* Compression may only consume published (VALIDATED/CONTESTED) knowledge,
  keeps source ids/versions/sample counts/counterexamples/invalidation
  conditions/known_at, and refuses absolute trading rules.
* ``CANDIDATE``, ``REVOKED``, ``EXPIRED`` and future ``known_at`` knowledge is
  excluded from default retrieval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select, update

from crypto_trader.learning.growth_contracts import (
    StructuredReview,
    bounded_text,
    canonical_json,
    sha256_text,
)
from crypto_trader.learning.growth_models import (
    GrowthCompressionORM,
    GrowthEpisodeBindingORM,
    GrowthLessonORM,
    GrowthPatternORM,
    utcnow,
)
from crypto_trader.learning.growth_review import (
    STATUS_SUCCEEDED,
    ReviewAttempt,
)
from crypto_trader.persistence.models import AICoinProfileORM, DailyReviewRunORM

LESSON_CANDIDATE = "CANDIDATE"
LESSON_VALIDATED = "VALIDATED"
LESSON_CONTESTED = "CONTESTED"
LESSON_REVOKED = "REVOKED"
LESSON_EXPIRED = "EXPIRED"
LESSON_QUARANTINED = "QUARANTINED"
LESSON_STAGED = "STAGED"
STAGED_REASON_PREFIX = "STAGED:"

PATTERN_CANDIDATE = LESSON_CANDIDATE
PATTERN_VALIDATED = LESSON_VALIDATED
PATTERN_CONTESTED = LESSON_CONTESTED
PATTERN_REVOKED = LESSON_REVOKED
PATTERN_EXPIRED = LESSON_EXPIRED
PATTERN_STAGED = LESSON_STAGED

COMPRESSION_PUBLISHED = "PUBLISHED"
COMPRESSION_REVOKED = LESSON_REVOKED
COMPRESSION_EXPIRED = LESSON_EXPIRED

RETRIEVABLE_STATUSES = {LESSON_VALIDATED, LESSON_CONTESTED}


def _stage_token_for(row) -> str | None:
    """Return the staging token for a staged lesson/pattern row."""
    if isinstance(row, GrowthPatternORM):
        features = row.features_json or {}
        return str(features.get("stage_token")) if features.get("staged") else None
    status_reason = getattr(row, "status_reason", None) or ""
    if status_reason.startswith(STAGED_REASON_PREFIX):
        return status_reason[len(STAGED_REASON_PREFIX):]
    return None


def _is_staged_row(row) -> bool:
    if isinstance(row, GrowthPatternORM):
        return bool((row.features_json or {}).get("staged"))
    return getattr(row, "status", None) == LESSON_STAGED


def _authoritative_only(rows):
    return [row for row in rows if not _is_staged_row(row)]

def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive DATETIME values; normalize before comparing."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


_ABSOLUTE_RULE = re.compile(
    r"\b(always|never|must|guaranteed?|risk[- ]free|all\s+trades|no\s+exceptions)\b",
    re.IGNORECASE,
)


def contains_absolute_rule(text: str) -> bool:
    return bool(_ABSOLUTE_RULE.search(text or ""))


@dataclass(frozen=True)
class EpisodeBinding:
    account_id: str
    mode: str
    currency: str
    instrument_id: str
    source_revision: str
    terminal_reason: str = "UNKNOWN"
    funding_provenance: str = "PROVEN"
    proof_kind: str = "FACTUAL_EPISODE"
    regime: str | None = None
    direction: str | None = None


@dataclass
class PublishReport:
    lessons: int = 0
    lessons_revised: int = 0
    pattern_id: str | None = None
    pattern_status: str | None = None
    pattern_version: int | None = None
    profile_version: int | None = None
    published_count: int = 0
    staged_patterns: list[dict[str, Any]] = dc_field(default_factory=list)


def lesson_logical_id(episode_id: str, statement: str) -> str:
    normalized = " ".join((statement or "").lower().split())
    return f"lesson_{sha256_text(episode_id + '|' + normalized)[:40]}"


def proposition_identity(statement: str, scope: dict[str, Any]) -> str:
    """Deterministic proposition identity for a testable lesson.

    Different hypotheses in the same symbol/regime/direction scope must not
    reinforce each other.  The identity binds the normalized proposition to
    its applicability conditions; polarity/contrary status is intentionally
    not part of the key so a contrary observation of the same proposition
    still lands in the same pattern.
    """
    # Preserve semantic characters (comparison operators, punctuation) so
    # "RSI > 70" and "RSI < 70" can never collapse to one identity.
    normalized = " ".join((statement or "").casefold().split())
    applicability = {
        key: scope.get(key)
        for key in ("scope", "symbols", "regimes", "directions")
        if scope.get(key)
    }
    raw = canonical_json(
        {"proposition": normalized, "applicability": applicability}
    )
    return f"prop_{sha256_text(raw)[:32]}"


def pattern_logical_id(
    account_id: str,
    mode: str,
    symbol: str,
    regime: str,
    direction: str,
    proposition_key: str = "legacy",
) -> str:
    raw = "|".join(
        (account_id, mode, symbol, regime, direction, proposition_key or "legacy")
    )
    return f"pattern_{sha256(raw.encode('utf-8')).hexdigest()[:40]}"


def compression_logical_id(account_id: str, mode: str, scope_key: str) -> str:
    raw = "|".join((account_id, mode, scope_key))
    return f"compression_{sha256(raw.encode('utf-8')).hexdigest()[:40]}"


class KnowledgeStore:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    # ------------------------------------------------------------------
    async def _current_row(self, model, logical_column, logical_id: str, *, as_of=None):
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(model)
                    .where(logical_column == logical_id)
                    .order_by(model.version.desc(), model.id.desc())
                )
            ).scalars().all()
        for row in rows:
            if _is_staged_row(row):
                continue
            known = _aware(getattr(row, "known_at", None))
            if as_of is not None and known is not None and known > as_of:
                continue
            return row
        return None

    async def current_lesson(
        self, lesson_id: str, *, as_of=None
    ) -> GrowthLessonORM | None:
        return await self._current_row(
            GrowthLessonORM, GrowthLessonORM.lesson_id, lesson_id, as_of=as_of
        )

    async def current_pattern(
        self, pattern_id: str, *, as_of=None
    ) -> GrowthPatternORM | None:
        return await self._current_row(
            GrowthPatternORM, GrowthPatternORM.pattern_id, pattern_id, as_of=as_of
        )

    async def current_compression(
        self, compression_id: str, *, as_of=None
    ) -> GrowthCompressionORM | None:
        return await self._current_row(
            GrowthCompressionORM,
            GrowthCompressionORM.compression_id,
            compression_id,
            as_of=as_of,
        )

    # ------------------------------------------------------------------
    async def upsert_lesson(self, values: dict) -> tuple[GrowthLessonORM, bool]:
        lesson_id = values["lesson_id"]
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(GrowthLessonORM)
                    .where(GrowthLessonORM.lesson_id == lesson_id)
                    .order_by(GrowthLessonORM.version.desc())
                )
            ).scalars().all()
            current = next((row for row in rows if not _is_staged_row(row)), None)
            if (
                current is not None
                and current.content_hash == values.get("content_hash")
                and current.status == values.get("status", current.status)
            ):
                return current, False
            version = (current.version if current else 0) + 1
            row = GrowthLessonORM(
                **values,
                version=version,
                supersedes_version_id=current.id if current is not None else None,
            )
            session.add(row)
            await session.commit()
            return row, True

    async def upsert_pattern(self, values: dict) -> tuple[GrowthPatternORM, bool]:
        pattern_id = values["pattern_id"]
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(GrowthPatternORM)
                    .where(GrowthPatternORM.pattern_id == pattern_id)
                    .order_by(GrowthPatternORM.version.desc())
                )
            ).scalars().all()
            current = next((row for row in rows if not _is_staged_row(row)), None)
            if (
                current is not None
                and current.content_hash == values.get("content_hash")
                and current.status == values.get("status", current.status)
            ):
                return current, False
            version = (current.version if current else 0) + 1
            row = GrowthPatternORM(**values, version=version)
            session.add(row)
            await session.commit()
            return row, True

    async def upsert_compression(self, values: dict) -> tuple[GrowthCompressionORM, bool]:
        compression_id = values["compression_id"]
        async with self.session_factory() as session:
            current = (
                await session.execute(
                    select(GrowthCompressionORM)
                    .where(GrowthCompressionORM.compression_id == compression_id)
                    .order_by(GrowthCompressionORM.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if current is not None and current.source_set_hash == values.get("source_set_hash"):
                return current, False
            version = (current.version if current else 0) + 1
            row = GrowthCompressionORM(**values, version=version)
            session.add(row)
            await session.commit()
            return row, True

    async def _next_version(self, model, logical_column, logical_id: str) -> int:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(model.version).where(logical_column == logical_id)
                )
            ).scalars().all()
        return (max(rows) if rows else 0) + 1

    async def stage_lesson(
        self, values: dict, *, stage_token: str
    ) -> GrowthLessonORM:
        """Persist a lesson candidate as staged; it is invisible until adoption."""
        version = await self._next_version(
            GrowthLessonORM, GrowthLessonORM.lesson_id, values["lesson_id"]
        )
        values = {
            key: value
            for key, value in values.items()
            if key not in {"status", "status_reason"}
        }
        async with self.session_factory() as session:
            row = GrowthLessonORM(
                **values,
                version=version,
                status=LESSON_STAGED,
                status_reason=f"{STAGED_REASON_PREFIX}{stage_token}",
            )
            session.add(row)
            await session.commit()
            return row, True

    async def stage_pattern(
        self, values: dict, *, stage_token: str
    ) -> GrowthPatternORM:
        """Persist a pattern candidate as staged; it is invisible until adoption."""
        version = await self._next_version(
            GrowthPatternORM, GrowthPatternORM.pattern_id, values["pattern_id"]
        )
        features = dict(values.get("features_json") or {})
        features.update({"staged": True, "stage_token": stage_token})
        values = {
            key: value
            for key, value in values.items()
            if key not in {"status", "status_reason"}
        }
        async with self.session_factory() as session:
            row = GrowthPatternORM(
                **{**values, "features_json": features},
                version=version,
                status=PATTERN_STAGED,
                status_reason="STAGED_PENDING_FENCED_ACTIVATION",
            )
            session.add(row)
            await session.commit()
            return row, True

    async def staged_rows(self, stage_token: str):
        async with self.session_factory() as session:
            lessons = (
                await session.execute(
                    select(GrowthLessonORM).where(
                        GrowthLessonORM.status == LESSON_STAGED,
                        GrowthLessonORM.status_reason
                        == f"{STAGED_REASON_PREFIX}{stage_token}",
                    )
                )
            ).scalars().all()
            patterns = (
                await session.execute(
                    select(GrowthPatternORM).where(
                        GrowthPatternORM.status == PATTERN_STAGED
                    )
                )
            ).scalars().all()
        patterns = [
            row for row in patterns if _stage_token_for(row) == stage_token
        ]
        return list(lessons), list(patterns)

    async def version_row(self, model, logical_column, logical_id: str, version: int):
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(model).where(
                        logical_column == logical_id, model.version == version
                    )
                )
            ).scalar_one_or_none()

    # ------------------------------------------------------------------
    async def current_lessons_for_scope(
        self,
        *,
        account_id: str,
        mode: str,
        symbol: str | None = None,
        regime: str | None = None,
        direction: str | None = None,
        include_candidates: bool = True,
        as_of: datetime | None = None,
        include_stage_token: str | None = None,
    ) -> list[GrowthLessonORM]:
        conditions = [
            GrowthLessonORM.account_id == account_id,
            GrowthLessonORM.mode == mode,
        ]
        if symbol is not None:
            conditions.append(GrowthLessonORM.symbol == symbol)
        if regime is not None:
            conditions.append(GrowthLessonORM.regime == regime)
        if direction is not None:
            conditions.append(GrowthLessonORM.direction == direction)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(GrowthLessonORM)
                    .where(*conditions)
                    .order_by(GrowthLessonORM.version.desc(), GrowthLessonORM.id.desc())
                )
            ).scalars().all()
        latest: dict[str, GrowthLessonORM] = {}
        for row in rows:
            if _is_staged_row(row) and _stage_token_for(row) != include_stage_token:
                continue
            known = _aware(row.known_at)
            if as_of is not None and known is not None and known > as_of:
                continue
            latest.setdefault(row.lesson_id, row)
        result = []
        for row in latest.values():
            if not include_candidates and row.status not in RETRIEVABLE_STATUSES:
                continue
            result.append(row)
        return result

    async def current_patterns_for_scope(
        self,
        *,
        account_id: str,
        mode: str,
        symbol: str | None = None,
        regime: str | None = None,
        direction: str | None = None,
        statuses: set[str] | None = None,
        as_of: datetime | None = None,
        include_stage_token: str | None = None,
    ) -> list[GrowthPatternORM]:
        conditions = [
            GrowthPatternORM.account_id == account_id,
            GrowthPatternORM.mode == mode,
        ]
        if symbol is not None:
            conditions.append(
                or_(GrowthPatternORM.symbol.is_(None), GrowthPatternORM.symbol == symbol)
            )
        if regime is not None:
            conditions.append(GrowthPatternORM.regime == regime)
        if direction is not None:
            conditions.append(
                or_(GrowthPatternORM.direction.is_(None), GrowthPatternORM.direction == direction)
            )
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(GrowthPatternORM)
                    .where(*conditions)
                    .order_by(GrowthPatternORM.version.desc(), GrowthPatternORM.id.desc())
                )
            ).scalars().all()
        latest: dict[str, GrowthPatternORM] = {}
        for row in rows:
            if _is_staged_row(row) and _stage_token_for(row) != include_stage_token:
                continue
            known = _aware(row.known_at)
            if as_of is not None and known is not None and known > as_of:
                continue
            latest.setdefault(row.pattern_id, row)
        result = []
        for row in latest.values():
            if statuses is not None and row.status not in statuses:
                continue
            result.append(row)
        return result


class GrowthKnowledgePublisher:
    def __init__(self, session_factory, *, min_pattern_samples: int = 3) -> None:
        self.session_factory = session_factory
        self.store = KnowledgeStore(session_factory)
        self.min_pattern_samples = max(1, min_pattern_samples)
        self._stage_token: str | None = None

    # ------------------------------------------------------------------
    async def publish_review(
        self,
        *,
        attempt: ReviewAttempt,
        binding: EpisodeBinding,
        known_at: datetime | None = None,
        staged: bool = False,
        stage_token: str | None = None,
    ) -> PublishReport:
        if attempt.status != STATUS_SUCCEEDED or attempt.review is None:
            raise ValueError("only a SUCCEEDED structured review can be published")
        if attempt.account_id and attempt.account_id != binding.account_id:
            raise ValueError("attempt account does not match binding account")
        known_at = known_at or utcnow()
        stage_token = stage_token or self._stage_token
        if staged and not stage_token:
            stage_token = f"stage_{uuid4().hex}"
        report = PublishReport()
        review: StructuredReview = attempt.review

        for lesson in review.testable_lessons:
            statement = bounded_text(lesson.statement)
            if contains_absolute_rule(statement):
                raise ValueError("ABSOLUTE_RULE_LANGUAGE")
            scope = dict(
                lesson.scope
                or review.applicability_scope
                or self._default_scope(binding)
            )
            scope["proposition_key"] = proposition_identity(statement, scope)
            proposition_key = scope["proposition_key"]
            content_hash = sha256_text(
                canonical_json(
                    {
                        "statement": statement,
                        "observation_refs": lesson.evidence_refs,
                        "support_refs": lesson.evidence_refs,
                        "contrary_refs": lesson.contrary_refs,
                        "scope": scope,
                        "proposition_key": proposition_key,
                    }
                )
            )
            lesson_values = {
                    "lesson_id": lesson_logical_id(
                        attempt.review.episode_id, statement
                    ),
                    "source_kind": "EPISODE",
                    "source_id": attempt.review.episode_id,
                    "review_attempt_id": attempt.attempt_id,
                    "episode_id": attempt.review.episode_id,
                    "account_id": binding.account_id,
                    "mode": binding.mode,
                    "symbol": binding.instrument_id,
                    "direction": binding.direction if binding.direction else None,
                    "regime": binding.regime,
                    "statement": statement,
                    "observation_refs_json": list(lesson.evidence_refs),
                    "support_refs_json": list(lesson.evidence_refs),
                    "contrary_refs_json": list(lesson.contrary_refs),
                    "scope_json": scope,
                    "content_hash": content_hash,
                    "status": LESSON_CANDIDATE,
                    "status_reason": "SINGLE_CASE_CANDIDATE",
                    "sample_count": 1,
                    "independent_sample_count": 1,
                    "data_completeness": (
                        "COMPLETE" if binding.funding_provenance == "PROVEN" else "UNKNOWN"
                    ),
                    "measurement_quality": (
                        "FILL_DERIVED"
                        if binding.proof_kind == "FACTUAL_EPISODE"
                        else "LEGACY_UNPROVEN"
                    ),
                    "hypothesis_support": (
                        "CONTESTED" if lesson.contrary_refs else "TESTABLE"
                    ),
                    "confidence": None,
                    "known_at": known_at,
            }
            if staged:
                row, created = await self.store.stage_lesson(
                    lesson_values, stage_token=stage_token or ""
                )
            else:
                row, created = await self.store.upsert_lesson(lesson_values)
            report.lessons += 1
            if created:
                report.lessons_revised += 1

        patterns = await self._rebuild_pattern(
            attempt=attempt,
            binding=binding,
            known_at=known_at,
            staged=staged,
            stage_token=stage_token,
        )
        if patterns:
            pattern, pattern_created = patterns[0]
            report.pattern_id = pattern.pattern_id
            report.pattern_status = (
                (pattern.features_json or {}).get("staged_status") or pattern.status
            )
            report.pattern_version = pattern.version
            for pattern, pattern_created in patterns:
                if pattern_created:
                    report.published_count += 1
                    report.pattern_version = pattern.version
                if staged:
                    report.staged_patterns.append(
                        {
                            "row_id": pattern.id,
                            "intended_status": (pattern.features_json or {}).get(
                                "staged_status"
                            ),
                            "intended_grade": (pattern.features_json or {}).get(
                                "staged_grade"
                            ),
                            "intended_reason": (pattern.features_json or {}).get(
                                "staged_reason"
                            ),
                            "known_at": known_at,
                        }
                    )

        if not staged:
            profile = await self._update_coin_profile(
                binding.instrument_id, known_at=known_at
            )
            if profile is not None:
                report.profile_version = profile.version
        return report

    async def publish_attempts(
        self,
        attempts: list[ReviewAttempt],
        *,
        bindings: dict[str, EpisodeBinding] | None = None,
        known_at: datetime | None = None,
        claim_context: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        """Stage all knowledge first, then activate it in one fenced transaction.

        Staged patterns/lessons are CANDIDATE and therefore not retrievable.
        The single activation transaction performs the live claim CAS together
        with every visibility transition; a stale claim rolls the transaction
        back and leaves zero newly retrievable knowledge.
        """
        report = PublishReport()
        binding_map = bindings or {}
        stage_token = f"stage_{uuid4().hex}"
        self._stage_token = stage_token
        for attempt in attempts:
            if attempt.status != STATUS_SUCCEEDED or attempt.review is None:
                continue
            episode_id = attempt.review.episode_id
            binding = binding_map.get(episode_id) or EpisodeBinding(
                account_id=attempt.account_id or "default",
                mode=attempt.mode or "PAPER",
                currency=attempt.currency or "USDT",
                instrument_id=attempt.symbol or "UNKNOWN",
                source_revision="UNKNOWN",
                funding_provenance="PROVEN",
            )
            one = await self.publish_review(
                attempt=attempt,
                binding=binding,
                known_at=known_at,
                staged=True,
                stage_token=stage_token,
            )
            report.lessons += one.lessons
            report.lessons_revised += one.lessons_revised
            report.published_count += one.published_count
            report.pattern_id = one.pattern_id or report.pattern_id
            report.pattern_status = one.pattern_status or report.pattern_status
            report.pattern_version = one.pattern_version or report.pattern_version
            report.profile_version = one.profile_version or report.profile_version
            report.staged_patterns.extend(one.staged_patterns)

        try:
            activated = await self._activate_staged(
                stage_token, claim_context=claim_context
            )
        finally:
            self._stage_token = None
        report.published_count = max(report.published_count, activated)
        return {
            "lessons": report.lessons,
            "lessons_revised": report.lessons_revised,
            "pattern_id": report.pattern_id,
            "pattern_status": report.pattern_status,
            "pattern_version": report.pattern_version,
            "profile_version": report.profile_version,
            "published_count": report.published_count,
        }

    def as_pipeline_publisher(self, bindings: dict[str, EpisodeBinding] | None = None):
        """Return an async publisher compatible with GrowthLearningPipeline."""
        from crypto_trader.learning.growth_pipeline import (
            STAGE_CLAIM_LOST,
            STAGE_SUCCEEDED,
            StageOutcome,
        )

        async def publisher(stats, review_attempts, *, fence) -> StageOutcome:
            if not await fence():
                return StageOutcome(STAGE_CLAIM_LOST, detail="claim lost before publish")
            claim_context = getattr(fence, "claim_context", None)
            try:
                report = await self.publish_attempts(
                    review_attempts,
                    bindings=bindings,
                    claim_context=claim_context,
                )
            except Exception as exc:
                from crypto_trader.learning.growth_experience import ClaimLostError

                if isinstance(exc, ClaimLostError):
                    return StageOutcome(
                        STAGE_CLAIM_LOST, detail="claim lost during staged activation"
                    )
                raise
            return StageOutcome(
                STAGE_SUCCEEDED,
                payload={
                    "published_count": int(report.get("published_count", 0)),
                    "report": report,
                },
            )

        return publisher

    @staticmethod
    def _lesson_copy_values(
        row: GrowthLessonORM, *, version: int, status: str, reason: str
    ) -> dict:
        return {
            "lesson_id": row.lesson_id,
            "version": version,
            "source_kind": row.source_kind,
            "source_id": row.source_id,
            "review_attempt_id": row.review_attempt_id,
            "episode_id": row.episode_id,
            "account_id": row.account_id,
            "mode": row.mode,
            "symbol": row.symbol,
            "direction": row.direction,
            "regime": row.regime,
            "statement": row.statement,
            "observation_refs_json": row.observation_refs_json,
            "support_refs_json": row.support_refs_json,
            "contrary_refs_json": row.contrary_refs_json,
            "scope_json": row.scope_json,
            "content_hash": row.content_hash,
            "status": status,
            "status_reason": reason,
            "sample_count": row.sample_count,
            "independent_sample_count": row.independent_sample_count,
            "data_completeness": row.data_completeness,
            "measurement_quality": row.measurement_quality,
            "hypothesis_support": (
                "SUPPORTED"
                if status == LESSON_VALIDATED
                else "CONTESTED"
                if status == LESSON_CONTESTED
                else row.hypothesis_support
            ),
            "confidence": row.confidence,
            "known_at": row.known_at,
            "valid_until": row.valid_until,
        }

    @staticmethod
    def _pattern_copy_values(
        row: GrowthPatternORM, *, version: int, status: str, grade: str, reason: str
    ) -> dict:
        features = dict(row.features_json or {})
        features.pop("staged", None)
        features.pop("stage_token", None)
        return {
            "pattern_id": row.pattern_id,
            "version": version,
            "account_id": row.account_id,
            "mode": row.mode,
            "symbol": row.symbol,
            "regime": row.regime,
            "direction": row.direction,
            "pattern_key": row.pattern_key,
            "features_json": features,
            "scope_json": row.scope_json,
            "sample_count": row.sample_count,
            "independent_sample_count": row.independent_sample_count,
            "support_count": row.support_count,
            "contrary_count": row.contrary_count,
            "breakeven_count": row.breakeven_count,
            "success_refs_json": row.success_refs_json,
            "contrary_refs_json": row.contrary_refs_json,
            "support_grade": grade,
            "content_hash": row.content_hash,
            "status": status,
            "status_reason": reason,
            "known_at": row.known_at,
            "valid_until": row.valid_until,
        }

    async def _next_version_in_session(self, session, model, logical_column, logical_id):
        rows = (
            await session.execute(
                select(model.version).where(logical_column == logical_id)
            )
        ).scalars().all()
        return (max(rows) if rows else 0) + 1

    async def _activate_staged(
        self,
        stage_token: str,
        *,
        claim_context: tuple[str, str, str] | None = None,
    ) -> int:
        """Adopt exactly one staging token inside one fenced transaction.

        Staged rows never participate in authoritative visibility.  The claim
        CAS and every authoritative insert happen in the same transaction; a
        stale claim rolls everything back and leaves the staged rows isolated
        and unactivated.
        """
        from sqlalchemy import and_

        from crypto_trader.learning.growth_experience import ClaimLostError

        activated = 0
        async with self.session_factory() as session:
            if claim_context is not None:
                review_date, claim_token, owner = claim_context
                now = utcnow()
                deadline = now + timedelta(seconds=1800)
                result = await session.execute(
                    update(DailyReviewRunORM)
                    .where(
                        and_(
                            DailyReviewRunORM.review_date == review_date,
                            DailyReviewRunORM.claim_token == claim_token,
                            DailyReviewRunORM.owner == owner,
                            DailyReviewRunORM.status.in_(("RUNNING", "SUCCEEDED")),
                            or_(
                                DailyReviewRunORM.claim_deadline_at.is_(None),
                                DailyReviewRunORM.claim_deadline_at >= now,
                            ),
                        )
                    )
                    .values(
                        claim_deadline_at=deadline,
                        last_attempt_at=now,
                    )
                )
                if result.rowcount != 1:
                    await session.rollback()
                    raise ClaimLostError("claim lost before staged activation")
            staged_lessons = (
                await session.execute(
                    select(GrowthLessonORM).where(
                        GrowthLessonORM.status == LESSON_STAGED,
                        GrowthLessonORM.status_reason
                        == f"{STAGED_REASON_PREFIX}{stage_token}",
                    )
                )
            ).scalars().all()
            staged_patterns = (
                await session.execute(
                    select(GrowthPatternORM).where(
                        GrowthPatternORM.status == PATTERN_STAGED
                    )
                )
            ).scalars().all()
            staged_patterns = [
                row for row in staged_patterns if _stage_token_for(row) == stage_token
            ]
            if not staged_lessons and not staged_patterns:
                return 0

            activated_lesson_ids: set[str] = set()
            for pattern in staged_patterns:
                features = dict(pattern.features_json or {})
                intended_status = str(
                    features.get("staged_status") or PATTERN_CANDIDATE
                )
                intended_grade = str(
                    features.get("staged_grade") or pattern.support_grade or "INSUFFICIENT"
                )
                intended_reason = str(
                    features.get("staged_reason") or intended_status
                )
                proposition_key = str(
                    (pattern.scope_json or {}).get("proposition_key")
                    or features.get("proposition_key")
                    or "legacy"
                )
                version = await self._next_version_in_session(
                    session,
                    GrowthPatternORM,
                    GrowthPatternORM.pattern_id,
                    pattern.pattern_id,
                )
                session.add(
                    GrowthPatternORM(
                        **self._pattern_copy_values(
                            pattern,
                            version=version,
                            status=intended_status,
                            grade=intended_grade,
                            reason=intended_reason,
                        )
                    )
                )
                activated += 1
                if intended_status not in {PATTERN_VALIDATED, PATTERN_CONTESTED}:
                    continue
                target_lesson_status = (
                    LESSON_VALIDATED
                    if intended_status == PATTERN_VALIDATED
                    else LESSON_CONTESTED
                )
                episode_ids = set(pattern.success_refs_json or []) | set(
                    pattern.contrary_refs_json or []
                )
                for lesson in staged_lessons:
                    if (
                        lesson.account_id != pattern.account_id
                        or lesson.mode != pattern.mode
                        or lesson.symbol != pattern.symbol
                        or (lesson.regime or "UNKNOWN") != (pattern.regime or "UNKNOWN")
                        or (lesson.direction or "UNKNOWN")
                        != (pattern.direction or "UNKNOWN")
                        or (lesson.episode_id or lesson.source_id) not in episode_ids
                    ):
                        continue
                    lesson_key = str(
                        (lesson.scope_json or {}).get("proposition_key") or "legacy"
                    )
                    if lesson_key != proposition_key:
                        continue
                    if lesson.lesson_id in activated_lesson_ids:
                        continue
                    lesson_version = await self._next_version_in_session(
                        session,
                        GrowthLessonORM,
                        GrowthLessonORM.lesson_id,
                        lesson.lesson_id,
                    )
                    session.add(
                        GrowthLessonORM(
                            **self._lesson_copy_values(
                                lesson,
                                version=lesson_version,
                                status=target_lesson_status,
                                reason=(
                                    "PATTERN_VALIDATED_INDEPENDENT_SAMPLES"
                                    if target_lesson_status == LESSON_VALIDATED
                                    else "PATTERN_CONTESTED_INDEPENDENT_SAMPLES"
                                ),
                            )
                        )
                    )
                    activated_lesson_ids.add(lesson.lesson_id)

            for lesson in staged_lessons:
                if lesson.lesson_id in activated_lesson_ids:
                    continue
                lesson_version = await self._next_version_in_session(
                    session,
                    GrowthLessonORM,
                    GrowthLessonORM.lesson_id,
                    lesson.lesson_id,
                )
                session.add(
                    GrowthLessonORM(
                        **self._lesson_copy_values(
                            lesson,
                            version=lesson_version,
                            status=LESSON_CANDIDATE,
                            reason=(
                                "SINGLE_CASE_CANDIDATE"
                                if not lesson.contrary_refs_json
                                else "SINGLE_CASE_CONTRARY"
                            ),
                        )
                    )
                )

            for row in staged_lessons + staged_patterns:
                await session.delete(row)
            await session.commit()
        return activated

    # ------------------------------------------------------------------
    async def compress(
        self,
        *,
        account_id: str,
        mode: str,
        symbol: str | None = None,
        regime: str | None = None,
        direction: str | None = None,
        min_samples: int | None = None,
        known_at: datetime | None = None,
    ) -> GrowthCompressionORM | None:
        known_at = known_at or utcnow()
        min_samples = self.min_pattern_samples if min_samples is None else max(1, min_samples)
        patterns = await self.store.current_patterns_for_scope(
            account_id=account_id,
            mode=mode,
            symbol=symbol,
            regime=regime,
            direction=direction,
            statuses=RETRIEVABLE_STATUSES,
        )
        patterns = [
            pattern
            for pattern in patterns
            if pattern.sample_count >= min_samples
            and (_aware(pattern.known_at) or known_at) <= known_at
            and pattern.valid_until is None
        ]
        if not patterns:
            return None
        scope_json = self._scope_payload(symbol, regime, direction)
        scope_key = canonical_json(scope_json)
        source_rows = sorted(patterns, key=lambda row: (row.pattern_id, row.version))
        source_set_hash = sha256_text(
            canonical_json(
                [
                    {
                        "kind": "PATTERN",
                        "id": row.pattern_id,
                        "version": row.version,
                        "sample_count": row.sample_count,
                        "status": row.status,
                        "known_at": row.known_at.isoformat(),
                    }
                    for row in source_rows
                ]
            )
        )
        compression_id = compression_logical_id(account_id, mode, scope_key)
        current = await self.store.current_compression(compression_id)
        if current is not None and current.source_set_hash == source_set_hash:
            return current

        statements: list[str] = []
        contrary_refs: list[str] = []
        for pattern in source_rows:
            contrary_refs.extend(list(pattern.contrary_refs_json or []))
            statements.extend(await self._statements_for_pattern(pattern, known_at=known_at))
        if any(contains_absolute_rule(statement) for statement in statements):
            raise ValueError("ABSOLUTE_RULE_LANGUAGE")
        statements = list(dict.fromkeys(statements))[:10]
        total_samples = sum(row.sample_count for row in source_rows)
        scope_label = scope_json.get("symbol") or "multi-symbol"
        title = f"Conditional experience: {scope_label} {regime or 'any regime'}"
        content = (
            f"Scope {canonical_json(scope_json)}. Across {total_samples} independent "
            f"factual episodes, the published evidence was consistent with: "
            + ("; ".join(statements) if statements else "no single dominant explanation")
            + ". This is a conditional hypothesis, not a trading rule. "
            "Counterexamples and invalidation conditions are recorded."
        )
        invalidation = [
            "new contradictory factual episodes in the same scope",
            "source pattern revoked, expired or superseded",
            "scope or source revision changes",
        ]
        row, _created = await self.store.upsert_compression(
            {
                "compression_id": compression_id,
                "account_id": account_id,
                "mode": mode,
                "title": bounded_text(title, 200),
                "content": bounded_text(content, 2000),
                "source_knowledge_json": [
                    {
                        "kind": "PATTERN",
                        "id": pattern.pattern_id,
                        "version": pattern.version,
                        "sample_count": pattern.sample_count,
                        "status": pattern.status,
                        "known_at": pattern.known_at.isoformat(),
                    }
                    for pattern in source_rows
                ],
                "source_set_hash": source_set_hash,
                "sample_count": total_samples,
                "contrary_refs_json": sorted(set(contrary_refs)),
                "invalidation_conditions_json": invalidation,
                "scope_json": scope_json,
                "content_hash": source_set_hash,
                "status": COMPRESSION_PUBLISHED,
                "known_at": known_at,
            }
        )
        return row

    # ------------------------------------------------------------------
    async def _statements_for_pattern(
        self, pattern: GrowthPatternORM, *, known_at: datetime
    ) -> list[str]:
        """Return statements only from the exact proposition membership.

        A lesson from the same episode but a different proposition (or an
        ineligible CANDIDATE version) must not borrow the pattern's validation.
        """
        episode_ids = set(pattern.success_refs_json or []) | set(
            pattern.contrary_refs_json or []
        )
        if not episode_ids:
            return []
        proposition_key = str(
            (pattern.scope_json or {}).get("proposition_key")
            or (pattern.features_json or {}).get("proposition_key")
            or "legacy"
        )
        conditions = [
            GrowthLessonORM.episode_id.in_(tuple(episode_ids)),
            GrowthLessonORM.account_id == pattern.account_id,
            GrowthLessonORM.mode == pattern.mode,
            GrowthLessonORM.known_at <= known_at,
            GrowthLessonORM.valid_until.is_(None),
            GrowthLessonORM.status.notin_(
                (LESSON_REVOKED, LESSON_EXPIRED, LESSON_QUARANTINED, LESSON_STAGED)
            ),
        ]
        if pattern.symbol is not None:
            conditions.append(GrowthLessonORM.symbol == pattern.symbol)
        if pattern.regime is not None:
            conditions.append(GrowthLessonORM.regime == pattern.regime)
        if pattern.direction is not None:
            conditions.append(GrowthLessonORM.direction == pattern.direction)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(GrowthLessonORM)
                    .where(*conditions)
                    .order_by(GrowthLessonORM.version.desc(), GrowthLessonORM.id.desc())
                )
            ).scalars().all()
        latest: dict[str, GrowthLessonORM] = {}
        for row in rows:
            latest.setdefault(row.lesson_id, row)
        out: list[str] = []
        for row in latest.values():
            lesson_key = str(
                (row.scope_json or {}).get("proposition_key") or "legacy"
            )
            if lesson_key != proposition_key:
                continue
            if row.status not in RETRIEVABLE_STATUSES:
                continue
            out.append(row.statement)
        return out

    async def _rebuild_pattern(
        self,
        *,
        attempt: ReviewAttempt,
        binding: EpisodeBinding,
        known_at: datetime,
        staged: bool = False,
        stage_token: str | None = None,
    ) -> list[tuple[GrowthPatternORM, bool]]:
        """Rebuild one pattern per proposition identity in this scope.

        Different testable propositions must not gain support from each
        other's episodes merely because symbol/regime/direction match.
        """
        review = attempt.review
        if review is None:
            return []
        regime = binding.regime or "UNKNOWN"
        direction = binding.direction or "UNKNOWN"
        lessons = await self.store.current_lessons_for_scope(
            account_id=binding.account_id,
            mode=binding.mode,
            symbol=None,
            regime=None,
            direction=None,
            as_of=known_at,
            include_stage_token=stage_token if staged else None,
        )
        scoped = [
            row
            for row in lessons
            if row.symbol == binding.instrument_id
            and (row.regime or "UNKNOWN") == regime
            and (row.direction or "UNKNOWN") == direction
            and (_aware(row.known_at) or known_at) <= known_at
            and row.status not in {LESSON_REVOKED, LESSON_EXPIRED, LESSON_QUARANTINED}
        ]
        current_episode_id = review.episode_id
        current_keys = {
            str((row.scope_json or {}).get("proposition_key") or "legacy")
            for row in scoped
            if (row.episode_id or row.source_id) == current_episode_id
        }
        if not current_keys:
            current_keys = {
                str((row.scope_json or {}).get("proposition_key") or "legacy")
                for row in scoped
            }
        if not current_keys:
            return []

        results: list[tuple[GrowthPatternORM, bool]] = []
        for proposition_key in sorted(current_keys):
            proposition_lessons = [
                row
                for row in scoped
                if str((row.scope_json or {}).get("proposition_key") or "legacy")
                == proposition_key
            ]
            by_episode: dict[str, dict[str, list[str]]] = {}
            for row in proposition_lessons:
                episode = row.episode_id or row.source_id
                bucket = by_episode.setdefault(episode, {"support": [], "contrary": []})
                refs = list(row.support_refs_json or [])
                contrary = list(row.contrary_refs_json or [])
                if contrary:
                    bucket["contrary"].extend(contrary)
                elif refs:
                    bucket["support"].extend(refs)
            support_episodes = {
                episode
                for episode, bucket in by_episode.items()
                if bucket["support"] and not bucket["contrary"]
            }
            contrary_episodes = {
                episode for episode, bucket in by_episode.items() if bucket["contrary"]
            }
            sample_count = len(by_episode)
            if sample_count == 0:
                continue
            independent = len(by_episode)
            if sample_count < self.min_pattern_samples:
                status, grade, reason = (
                    PATTERN_CANDIDATE,
                    "INSUFFICIENT",
                    "INDEPENDENT_SAMPLES_BELOW_MINIMUM",
                )
            elif not contrary_episodes:
                status, grade, reason = (
                    PATTERN_VALIDATED,
                    "SUPPORTED",
                    "NO_CONTRARY_EPISODES",
                )
            elif len(support_episodes) > len(contrary_episodes):
                status, grade, reason = (
                    PATTERN_CONTESTED,
                    "CONTESTED",
                    "CONTRARY_EPISODES_PRESENT",
                )
            else:
                status, grade, reason = (
                    PATTERN_CONTESTED,
                    "WEAK",
                    "CONTRARY_EPISODES_DOMINATE",
                )
            pattern_id = pattern_logical_id(
                binding.account_id,
                binding.mode,
                binding.instrument_id,
                regime,
                direction,
                proposition_key,
            )
            success_refs = sorted(support_episodes)
            contrary_refs = sorted(contrary_episodes)
            content_hash = sha256_text(
                canonical_json(
                    {
                        "pattern_id": pattern_id,
                        "proposition_key": proposition_key,
                        "scope": {
                            "account_id": binding.account_id,
                            "mode": binding.mode,
                            "symbol": binding.instrument_id,
                            "regime": regime,
                            "direction": direction,
                        },
                        "sample_count": sample_count,
                        "support": success_refs,
                        "contrary": contrary_refs,
                        "status": status,
                        "grade": grade,
                    }
                )
            )
            features = {
                "basis": "STRUCTURED_REVIEW_EVIDENCE_REFS",
                "profitability_used": False,
                "min_pattern_samples": self.min_pattern_samples,
                "proposition_key": proposition_key,
            }
            if staged:
                features.update(
                    {
                        "staged": True,
                        "staged_status": status,
                        "staged_grade": grade,
                        "staged_reason": reason,
                    }
                )
            pattern_values = {
                    "pattern_id": pattern_id,
                    "account_id": binding.account_id,
                    "mode": binding.mode,
                    "symbol": binding.instrument_id,
                    "regime": regime,
                    "direction": direction,
                    "pattern_key": (
                        f"{binding.account_id}:{binding.mode}:{binding.instrument_id}:"
                        f"{regime}:{direction}:{proposition_key}"
                    ),
                    "features_json": features,
                    "scope_json": {
                        **self._scope_payload(
                            binding.instrument_id, regime, direction
                        ),
                        "proposition_key": proposition_key,
                    },
                    "sample_count": sample_count,
                    "independent_sample_count": independent,
                    "support_count": len(support_episodes),
                    "contrary_count": len(contrary_episodes),
                    "breakeven_count": 0,
                    "success_refs_json": success_refs,
                    "contrary_refs_json": contrary_refs,
                    "support_grade": grade,
                    "content_hash": content_hash,
                    "status": status,
                    "status_reason": reason,
                    "known_at": known_at,
            }
            if staged:
                row, created = await self.store.stage_pattern(
                    pattern_values, stage_token=stage_token or ""
                )
            else:
                row, created = await self.store.upsert_pattern(pattern_values)
            if not staged:
                await self._sync_lessons_with_pattern(
                    row,
                    known_at=known_at,
                    episode_ids=set(success_refs) | set(contrary_refs),
                    proposition_key=proposition_key,
                )
            results.append((row, created))
        return results

    async def _sync_lessons_with_pattern(
        self,
        pattern: GrowthPatternORM,
        *,
        known_at: datetime,
        episode_ids: set[str],
        proposition_key: str | None = None,
    ) -> None:
        """Promote/downgrade lesson status only when the independent pattern does.

        A single-case lesson stays CANDIDATE; it becomes VALIDATED/CONTESTED
        only with the pattern's independent sample verdict.  PnL is not used.
        """
        if not episode_ids or pattern.status not in {PATTERN_VALIDATED, PATTERN_CONTESTED}:
            return
        lessons = await self.store.current_lessons_for_scope(
            account_id=pattern.account_id,
            mode=pattern.mode,
            symbol=pattern.symbol,
            regime=pattern.regime,
            direction=pattern.direction,
        )
        target_status = (
            PATTERN_VALIDATED if pattern.status == PATTERN_VALIDATED else PATTERN_CONTESTED
        )
        reason = (
            "PATTERN_VALIDATED_INDEPENDENT_SAMPLES"
            if target_status == PATTERN_VALIDATED
            else "PATTERN_CONTESTED_INDEPENDENT_SAMPLES"
        )
        for lesson in lessons:
            if (lesson.episode_id or lesson.source_id) not in episode_ids:
                continue
            if proposition_key is not None and str(
                (lesson.scope_json or {}).get("proposition_key") or "legacy"
            ) != proposition_key:
                continue
            if lesson.status == target_status and lesson.hypothesis_support == (
                "SUPPORTED" if target_status == PATTERN_VALIDATED else "CONTESTED"
            ):
                continue
            await self.store.upsert_lesson(
                {
                    "lesson_id": lesson.lesson_id,
                    "source_kind": lesson.source_kind,
                    "source_id": lesson.source_id,
                    "review_attempt_id": lesson.review_attempt_id,
                    "episode_id": lesson.episode_id,
                    "account_id": lesson.account_id,
                    "mode": lesson.mode,
                    "symbol": lesson.symbol,
                    "direction": lesson.direction,
                    "regime": lesson.regime,
                    "statement": lesson.statement,
                    "observation_refs_json": lesson.observation_refs_json,
                    "support_refs_json": lesson.support_refs_json,
                    "contrary_refs_json": lesson.contrary_refs_json,
                    "scope_json": lesson.scope_json,
                    "content_hash": lesson.content_hash,
                    "status": target_status,
                    "status_reason": reason,
                    "sample_count": lesson.sample_count,
                    "independent_sample_count": lesson.independent_sample_count,
                    "data_completeness": lesson.data_completeness,
                    "measurement_quality": lesson.measurement_quality,
                    "hypothesis_support": (
                        "SUPPORTED" if target_status == PATTERN_VALIDATED else "CONTESTED"
                    ),
                    "confidence": lesson.confidence,
                    "known_at": known_at,
                }
            )

    async def _update_coin_profile(
        self, symbol: str, *, known_at: datetime
    ) -> AICoinProfileORM | None:
        async with self.session_factory() as session:
            lessons = (
                await session.execute(
                    select(GrowthLessonORM)
                    .where(
                        GrowthLessonORM.symbol == symbol,
                        GrowthLessonORM.known_at <= known_at,
                        GrowthLessonORM.valid_until.is_(None),
                    )
                    .order_by(GrowthLessonORM.id.desc())
                )
            ).scalars().all()
            patterns = (
                await session.execute(
                    select(GrowthPatternORM)
                    .where(
                        GrowthPatternORM.symbol == symbol,
                        GrowthPatternORM.known_at <= known_at,
                    )
                    .order_by(GrowthPatternORM.id.desc())
                )
            ).scalars().all()
            latest_lessons: dict[str, GrowthLessonORM] = {}
            for row in lessons:
                latest_lessons.setdefault(row.lesson_id, row)
            latest_patterns: dict[str, GrowthPatternORM] = {}
            for row in patterns:
                latest_patterns.setdefault(row.pattern_id, row)
            episode_ids = {
                row.episode_id or row.source_id
                for row in latest_lessons.values()
                if row.status not in {LESSON_REVOKED, LESSON_EXPIRED, LESSON_QUARANTINED}
            }
            supported = [
                row
                for row in latest_patterns.values()
                if row.status == PATTERN_VALIDATED
            ]
            contested = [
                row
                for row in latest_patterns.values()
                if row.status == PATTERN_CONTESTED
            ]
            tags = [
                f"SUPPORTED_PATTERNS:{len(supported)}",
                f"CONTESTED_PATTERNS:{len(contested)}",
                "EVIDENCE_BASED_PROFILE",
                "NOT_A_WIN_RATE",
            ]
            summary = (
                f"Descriptive profile from {len(episode_ids)} factual episodes: "
                f"{len(supported)} supported patterns, {len(contested)} contested patterns. "
                "Support is derived from structured-review evidence, not profitability."
            )
            best = [
                {
                    "pattern_id": row.pattern_id,
                    "regime": row.regime,
                    "direction": row.direction,
                    "sample_count": row.sample_count,
                    "version": row.version,
                }
                for row in supported
            ]
            worst = [
                {
                    "pattern_id": row.pattern_id,
                    "regime": row.regime,
                    "direction": row.direction,
                    "sample_count": row.sample_count,
                    "version": row.version,
                    "status_reason": row.status_reason,
                }
                for row in contested
            ]
            profile = (
                await session.execute(
                    select(AICoinProfileORM).where(AICoinProfileORM.symbol == symbol)
                )
            ).scalar_one_or_none()
            content_hash = sha256_text(
                canonical_json(
                    {
                        "summary": summary,
                        "tags": tags,
                        "best": best,
                        "worst": worst,
                    }
                )
            )
            if profile is None:
                profile = AICoinProfileORM(
                    symbol=symbol,
                    sample_count=len(episode_ids),
                    profile_summary=bounded_text(summary, 200),
                    behavior_tags_json=tags,
                    best_setups_json=best,
                    worst_setups_json=worst,
                    version=1,
                    updated_at=known_at,
                )
                session.add(profile)
            else:
                existing_hash = sha256_text(
                    canonical_json(
                        {
                            "summary": profile.profile_summary,
                            "tags": profile.behavior_tags_json,
                            "best": profile.best_setups_json,
                            "worst": profile.worst_setups_json,
                        }
                    )
                )
                if existing_hash != content_hash:
                    profile.sample_count = len(episode_ids)
                    profile.profile_summary = bounded_text(summary, 200)
                    profile.behavior_tags_json = tags
                    profile.best_setups_json = best
                    profile.worst_setups_json = worst
                    profile.version = (profile.version or 1) + 1
                    profile.updated_at = known_at
            await session.commit()
            return profile

    # ------------------------------------------------------------------
    async def revoke(self, *, kind: str, logical_id: str, reason: str, at=None):
        at = at or utcnow()
        model, column = self._model_for_kind(kind)
        current = await self.store._current_row(model, column, logical_id)
        if current is None:
            raise ValueError(f"unknown {kind} {logical_id}")
        if current.status == LESSON_REVOKED:
            return current
        values = {
            column.key: logical_id,
            "version": current.version + 1,
            "status": (
                LESSON_REVOKED
                if kind != "compression"
                else COMPRESSION_REVOKED
            ),
            "status_reason": bounded_text(reason, 255),
            "revoked_at": at,
            # Never backdate a revocation version: it becomes visible at the
            # transition time, so historical as_of before `at` still sees the
            # old validated version and after `at` sees revocation.
            "known_at": at,
        }
        for field in (
            "account_id",
            "mode",
            "symbol",
            "direction",
            "regime",
            "title",
            "content",
            "statement",
            "pattern_key",
        ):
            if hasattr(current, field):
                values[field] = getattr(current, field)
        for field in (
            "sample_count",
            "independent_sample_count",
            "support_count",
            "contrary_count",
            "breakeven_count",
            "content_hash",
            "source_set_hash",
        ):
            if hasattr(current, field):
                values[field] = getattr(current, field)
        for field in (
            "scope_json",
            "observation_refs_json",
            "support_refs_json",
            "contrary_refs_json",
            "success_refs_json",
            "source_knowledge_json",
            "invalidation_conditions_json",
            "features_json",
            "support_grade",
            "data_completeness",
            "measurement_quality",
            "hypothesis_support",
            "episode_id",
            "source_id",
            "source_kind",
            "review_attempt_id",
            "supersedes_version_id",
        ):
            if hasattr(current, field):
                values[field] = getattr(current, field)
        if hasattr(current, "supersedes_version_id"):
            values["supersedes_version_id"] = current.id
        async with self.session_factory() as session:
            row = model(**values)
            session.add(row)
            await session.commit()
        if kind == "pattern":
            episode_ids = set(current.success_refs_json or []) | set(
                current.contrary_refs_json or []
            )
            revoked_proposition = str(
                (current.scope_json or {}).get("proposition_key")
                or (current.features_json or {}).get("proposition_key")
                or "legacy"
            )
            lessons = await self.store.current_lessons_for_scope(
                account_id=current.account_id,
                mode=current.mode,
                symbol=current.symbol,
                regime=current.regime,
                direction=current.direction,
            )
            for lesson in lessons:
                if (lesson.episode_id or lesson.source_id) not in episode_ids:
                    continue
                lesson_proposition = str(
                    (lesson.scope_json or {}).get("proposition_key") or "legacy"
                )
                if lesson_proposition != revoked_proposition:
                    continue
                await self.store.upsert_lesson(
                    {
                        "lesson_id": lesson.lesson_id,
                        "source_kind": lesson.source_kind,
                        "source_id": lesson.source_id,
                        "review_attempt_id": lesson.review_attempt_id,
                        "episode_id": lesson.episode_id,
                        "account_id": lesson.account_id,
                        "mode": lesson.mode,
                        "symbol": lesson.symbol,
                        "direction": lesson.direction,
                        "regime": lesson.regime,
                        "statement": lesson.statement,
                        "observation_refs_json": lesson.observation_refs_json,
                        "support_refs_json": lesson.support_refs_json,
                        "contrary_refs_json": lesson.contrary_refs_json,
                        "scope_json": lesson.scope_json,
                        "content_hash": lesson.content_hash,
                        "status": LESSON_REVOKED,
                        "status_reason": "SOURCE_PATTERN_REVOKED",
                        "sample_count": lesson.sample_count,
                        "independent_sample_count": lesson.independent_sample_count,
                        "data_completeness": lesson.data_completeness,
                        "measurement_quality": lesson.measurement_quality,
                        "hypothesis_support": lesson.hypothesis_support,
                        "confidence": lesson.confidence,
                        "known_at": at,
                        "revoked_at": at,
                    }
                )
        return row

    async def expire(self, *, kind: str, logical_id: str, valid_until: datetime):
        model, column = self._model_for_kind(kind)
        current = await self.store._current_row(model, column, logical_id)
        if current is None:
            raise ValueError(f"unknown {kind} {logical_id}")
        values = {
            column.key: logical_id,
            "version": current.version + 1,
            "status": (
                LESSON_EXPIRED
                if kind == "lesson"
                else PATTERN_EXPIRED
                if kind == "pattern"
                else COMPRESSION_EXPIRED
            ),
            "status_reason": "VALID_UNTIL_REACHED",
            "valid_until": valid_until,
            # The expiry state is learned/applied at valid_until; historical
            # visibility before it must remain unchanged.
            "known_at": valid_until,
        }
        for field in (
            "account_id",
            "mode",
            "symbol",
            "direction",
            "regime",
            "title",
            "content",
            "statement",
            "pattern_key",
            "sample_count",
            "independent_sample_count",
            "support_count",
            "contrary_count",
            "breakeven_count",
            "content_hash",
            "source_set_hash",
            "scope_json",
            "observation_refs_json",
            "support_refs_json",
            "contrary_refs_json",
            "success_refs_json",
            "source_knowledge_json",
            "invalidation_conditions_json",
            "features_json",
            "support_grade",
            "episode_id",
            "source_id",
            "source_kind",
            "review_attempt_id",
        ):
            if hasattr(current, field):
                values[field] = getattr(current, field)
        if hasattr(current, "supersedes_version_id"):
            values["supersedes_version_id"] = current.id
        async with self.session_factory() as session:
            row = model(**values)
            session.add(row)
            await session.commit()
            return row

    @staticmethod
    def _model_for_kind(kind: str):
        mapping = {
            "lesson": (GrowthLessonORM, GrowthLessonORM.lesson_id),
            "pattern": (GrowthPatternORM, GrowthPatternORM.pattern_id),
            "compression": (GrowthCompressionORM, GrowthCompressionORM.compression_id),
        }
        if kind not in mapping:
            raise ValueError(f"unknown knowledge kind: {kind}")
        return mapping[kind]

    @staticmethod
    def _scope_payload(
        symbol: str | None, regime: str | None, direction: str | None
    ) -> dict[str, Any]:
        scope: dict[str, Any] = {"scope": "SYMBOL_REGIME"}
        if symbol:
            scope["symbols"] = [symbol]
        if regime:
            scope["regimes"] = [regime]
        if direction:
            scope["directions"] = [direction]
        return scope

    @staticmethod
    def _default_scope(binding: EpisodeBinding) -> dict[str, Any]:
        scope: dict[str, Any] = {"scope": "SYMBOL_REGIME"}
        if binding.instrument_id:
            scope["symbols"] = [binding.instrument_id]
        if binding.regime:
            scope["regimes"] = [binding.regime]
        if binding.direction:
            scope["directions"] = [binding.direction]
        return scope

    # ------------------------------------------------------------------
    async def list_published_lessons(
        self,
        *,
        account_id: str,
        mode: str,
        symbol: str | None = None,
        regime: str | None = None,
        as_of: datetime | None = None,
        statuses: set[str] | None = None,
        limit: int = 5,
    ) -> list[GrowthLessonORM]:
        as_of = as_of or datetime.now(UTC)
        rows = await self.store.current_lessons_for_scope(
            account_id=account_id, mode=mode, symbol=symbol, regime=regime, as_of=as_of
        )
        allowed = statuses or RETRIEVABLE_STATUSES
        return [
            row
            for row in rows
            if row.status in allowed
            and (_aware(row.known_at) or as_of) <= as_of
            and (row.valid_until is None or (_aware(row.valid_until) or as_of) > as_of)
        ][: max(1, limit)]

    async def list_published_patterns(
        self,
        *,
        account_id: str,
        mode: str,
        symbol: str | None = None,
        regime: str | None = None,
        as_of: datetime | None = None,
        statuses: set[str] | None = None,
        limit: int = 5,
    ) -> list[GrowthPatternORM]:
        as_of = as_of or datetime.now(UTC)
        rows = await self.store.current_patterns_for_scope(
            account_id=account_id, mode=mode, symbol=symbol, regime=regime, as_of=as_of
        )
        allowed = statuses or RETRIEVABLE_STATUSES
        return [
            row
            for row in rows
            if row.status in allowed
            and (_aware(row.known_at) or as_of) <= as_of
            and (row.valid_until is None or (_aware(row.valid_until) or as_of) > as_of)
        ][: max(1, limit)]

    async def list_published_compressions(
        self,
        *,
        account_id: str,
        mode: str,
        symbol: str | None = None,
        regime: str | None = None,
        as_of: datetime | None = None,
        limit: int = 5,
    ) -> list[GrowthCompressionORM]:
        as_of = as_of or datetime.now(UTC)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(GrowthCompressionORM)
                    .where(
                        GrowthCompressionORM.account_id == account_id,
                        GrowthCompressionORM.mode == mode,
                    )
                    .order_by(GrowthCompressionORM.id.desc())
                )
            ).scalars().all()
        latest: dict[str, GrowthCompressionORM] = {}
        for row in rows:
            known = _aware(row.known_at) or as_of
            if known > as_of:
                continue
            latest.setdefault(row.compression_id, row)
        out = []
        for row in latest.values():
            if row.status != COMPRESSION_PUBLISHED:
                continue
            scope = row.scope_json or {}
            if symbol and scope.get("symbols") and symbol not in scope["symbols"]:
                continue
            if regime and scope.get("regimes") and regime not in scope["regimes"]:
                continue
            out.append(row)
        return out[: max(1, limit)]

    async def record_binding(
        self,
        *,
        episode_id: str,
        binding: EpisodeBinding,
        revision: int = 1,
        known_at: datetime | None = None,
    ) -> GrowthEpisodeBindingORM:
        known_at = known_at or utcnow()
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(GrowthEpisodeBindingORM).where(
                        GrowthEpisodeBindingORM.episode_id == episode_id,
                        GrowthEpisodeBindingORM.revision == revision,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = GrowthEpisodeBindingORM(
                    episode_id=episode_id,
                    revision=revision,
                    account_id=binding.account_id,
                    currency=binding.currency,
                    instrument_id=binding.instrument_id,
                    mode=binding.mode,
                    source_revision=binding.source_revision,
                    terminal_reason=binding.terminal_reason,
                    known_at=known_at,
                )
                session.add(row)
                await session.commit()
            return row
