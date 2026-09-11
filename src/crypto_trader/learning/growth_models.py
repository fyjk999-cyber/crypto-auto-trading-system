"""Draft growth-learning schema (G02–G06).

Why a separate metadata instead of editing ``persistence.models``
-----------------------------------------------------------------
* The shared model file and the Alembic ``versions/`` directory are
  integration-owned/public files for this parallel task.  The existing ORM
  cannot express the required revisions, evidence references, stage status
  and import lineage (see ``docs/growth-system/MIGRATION_AND_ROLLBACK.md``
  for the field-gap table).
* This module defines an independent declarative metadata.  Tests create it
  on a throwaway SQLite database.  Production application of this schema
  remains a **draft** until the integration owner assigns an Alembic head and
  runs the migration matrix.

Nothing in this module mutates or migrates a production database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class ExactDecimal(TypeDecorator):
    """SQLite/JSON-safe exact decimal storage.

    The shared model has an equivalent type; this copy avoids importing the
    shared metadata while keeping tests portable to the same SQL dialect.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect) -> str | None:
        return None if value is None else format(value, "f")

    def process_result_value(self, value: str | None, dialect) -> Decimal | None:
        return None if value is None else Decimal(value)


class GrowthBase(DeclarativeBase):
    pass


class GrowthLearningJobORM(GrowthBase):
    """One durable, fenced learning job for an account/mode/date/revision."""

    __tablename__ = "growth_learning_jobs"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "mode",
            "review_date",
            "source_revision",
            "profile_version",
            "revision",
            name="uq_growth_job_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    review_date: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    stats_status: Mapped[str] = mapped_column(String(16), default="PENDING")
    review_status: Mapped[str] = mapped_column(String(16), default="PENDING")
    publish_status: Mapped[str] = mapped_column(String(16), default="PENDING")
    claim_token: Mapped[str | None] = mapped_column(String(64))
    claim_owner: Mapped[str | None] = mapped_column(String(64))
    claim_fence: Mapped[int] = mapped_column(Integer, default=0)
    claim_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error_type: Mapped[str | None] = mapped_column(String(64))
    last_error_detail_sanitized: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_revision: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class GrowthReviewAttemptORM(GrowthBase):
    """Every structured-review provider attempt, successful or failed."""

    __tablename__ = "growth_review_attempts"
    __table_args__ = (
        UniqueConstraint(
            "review_date",
            "episode_id",
            "profile_version",
            "input_hash",
            "attempt_no",
            name="uq_growth_review_attempt",
        ),
    )

    attempt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_date: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    episode_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_detail_sanitized: Mapped[str | None] = mapped_column(String(255))
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    usage_status: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    latency_ms: Mapped[float | None] = mapped_column(Float)
    retries: Mapped[int | None] = mapped_column(Integer)
    claim_token: Mapped[str | None] = mapped_column(String(64))
    owner: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GrowthEpisodeBindingORM(GrowthBase):
    """Account/currency/mode/instrument binding for a factual episode revision."""

    __tablename__ = "growth_episode_bindings"
    __table_args__ = (
        UniqueConstraint("episode_id", "revision", name="uq_growth_episode_binding"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    instrument_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    source_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    terminal_reason: Mapped[str | None] = mapped_column(String(255))
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GrowthLessonORM(GrowthBase):
    """A candidate/testable lesson with explicit evidence and status versions."""

    __tablename__ = "growth_lessons"
    __table_args__ = (UniqueConstraint("lesson_id", "version", name="uq_growth_lesson_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lesson_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_kind: Mapped[str] = mapped_column(String(16), default="EPISODE")
    source_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    review_attempt_id: Mapped[str | None] = mapped_column(String(64), index=True)
    episode_id: Mapped[str | None] = mapped_column(String(64), index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    direction: Mapped[str | None] = mapped_column(String(8))
    regime: Mapped[str | None] = mapped_column(String(64))
    statement: Mapped[str] = mapped_column(String(1000), nullable=False)
    observation_refs_json: Mapped[list[Any] | None] = mapped_column(JSON)
    support_refs_json: Mapped[list[Any] | None] = mapped_column(JSON)
    contrary_refs_json: Mapped[list[Any] | None] = mapped_column(JSON)
    scope_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="CANDIDATE", index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=1)
    independent_sample_count: Mapped[int] = mapped_column(Integer, default=1)
    data_completeness: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    measurement_quality: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    hypothesis_support: Mapped[str] = mapped_column(String(16), default="CANDIDATE")
    confidence: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    supersedes_version_id: Mapped[int | None] = mapped_column(Integer)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GrowthPatternORM(GrowthBase):
    """A pattern requires independent samples, contradiction accounting and scope."""

    __tablename__ = "growth_patterns"
    __table_args__ = (
        UniqueConstraint("pattern_id", "version", name="uq_growth_pattern_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    regime: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(8))
    pattern_key: Mapped[str] = mapped_column(String(128), nullable=False)
    features_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    scope_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    independent_sample_count: Mapped[int] = mapped_column(Integer, default=0)
    support_count: Mapped[int] = mapped_column(Integer, default=0)
    contrary_count: Mapped[int] = mapped_column(Integer, default=0)
    breakeven_count: Mapped[int] = mapped_column(Integer, default=0)
    success_refs_json: Mapped[list[Any] | None] = mapped_column(JSON)
    contrary_refs_json: Mapped[list[Any] | None] = mapped_column(JSON)
    support_grade: Mapped[str] = mapped_column(String(16), default="INSUFFICIENT")
    status: Mapped[str] = mapped_column(String(16), default="CANDIDATE", index=True)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GrowthCompressionORM(GrowthBase):
    """Compressed experience built only from published, versioned knowledge."""

    __tablename__ = "growth_compressions"
    __table_args__ = (
        UniqueConstraint(
            "compression_id", "version", name="uq_growth_compression_version"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    compression_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_knowledge_json: Mapped[list[Any] | None] = mapped_column(JSON)
    source_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    contrary_refs_json: Mapped[list[Any] | None] = mapped_column(JSON)
    invalidation_conditions_json: Mapped[list[Any] | None] = mapped_column(JSON)
    scope_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="PUBLISHED", index=True)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GrowthImportBatchORM(GrowthBase):
    __tablename__ = "growth_import_batches"

    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_db_path: Mapped[str] = mapped_column(String(500), nullable=False)
    source_db_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PLANNED", index=True)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    quarantined_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GrowthImportItemORM(GrowthBase):
    __tablename__ = "growth_import_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "namespace", name="uq_growth_import_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    source_table: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    target_kind: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GrowthLegacyObservationORM(GrowthBase):
    """Imported legacy knowledge, explicitly not canonical factual truth."""

    __tablename__ = "growth_legacy_observations"
    __table_args__ = (
        UniqueConstraint("observation_id", name="uq_growth_legacy_observation"),
    )

    observation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    direction: Mapped[str | None] = mapped_column(String(8))
    economic_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(24), default="LEGACY_OBSERVATION", index=True)
    source_json_sanitized: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class GrowthToolSelectionORM(GrowthBase):
    """Proof that a ChiefTrader decision selected and actually received memory evidence."""

    __tablename__ = "growth_tool_selections"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "mode", "context_id", name="uq_growth_tool_selection_context"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    selection_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    context_id: Mapped[str] = mapped_column(String(128), nullable=False)
    decision_id: Mapped[str | None] = mapped_column(String(64), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    selected_tools_json: Mapped[list[Any] | None] = mapped_column(JSON)
    returned_refs_json: Mapped[list[Any] | None] = mapped_column(JSON)
    evidence_package_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    tool_versions_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


GROWTH_TABLES = (
    GrowthLearningJobORM,
    GrowthReviewAttemptORM,
    GrowthEpisodeBindingORM,
    GrowthLessonORM,
    GrowthPatternORM,
    GrowthCompressionORM,
    GrowthImportBatchORM,
    GrowthImportItemORM,
    GrowthLegacyObservationORM,
    GrowthToolSelectionORM,
)


async def create_growth_schema(engine) -> None:
    """Create the draft growth tables on a throwaway/isolated database only."""

    async with engine.begin() as connection:
        await connection.run_sync(GrowthBase.metadata.create_all)


def growth_schema_sql() -> list[str]:
    """Return CREATE TABLE statements for the draft migration package."""

    from sqlalchemy.dialects import sqlite
    from sqlalchemy.schema import CreateTable

    return [
        str(CreateTable(table).compile(dialect=sqlite.dialect())).strip() + ";"
        for table in GROWTH_TABLES
    ]


__all__ = [
    "GROWTH_TABLES",
    "GrowthBase",
    "GrowthCompressionORM",
    "GrowthEpisodeBindingORM",
    "GrowthImportBatchORM",
    "GrowthImportItemORM",
    "GrowthLearningJobORM",
    "GrowthLegacyObservationORM",
    "GrowthLessonORM",
    "GrowthPatternORM",
    "GrowthReviewAttemptORM",
    "GrowthToolSelectionORM",
    "Boolean",
    "create_growth_schema",
    "growth_schema_sql",
]
