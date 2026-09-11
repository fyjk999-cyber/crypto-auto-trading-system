"""Growth V2 Adaptive Experience Card schema.

Revision ID: 0040_growth_v2_cards
Revises: 0039_applicability
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context as alembic_context
from alembic import op

revision = "0040_growth_v2_cards"
down_revision = "0039_applicability"
branch_labels = None
depends_on = None

_CARD_TABLE = "ai_compressed_experience"

_ADDED_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, object], ...] = (
    ("experience_type", sa.String(length=32), "COMPRESSED_EXPERIENCE"),
    ("account_id", sa.String(length=64), "default"),
    ("mode", sa.String(length=16), "PAPER"),
    ("share_scope", sa.String(length=32), "ACCOUNT_MODE"),
    ("trigger_signature_json", sa.JSON(), None),
    ("context_signature_json", sa.JSON(), None),
    ("factor_refs_json", sa.JSON(), None),
    ("guidance_json", sa.JSON(), None),
    ("source_episode_ids_json", sa.JSON(), None),
    ("supporting_episode_ids_json", sa.JSON(), None),
    ("contradicting_episode_ids_json", sa.JSON(), None),
    ("support_count", sa.Integer(), "0"),
    ("contradiction_count", sa.Integer(), "0"),
    ("confidence", sa.Numeric(), "0"),
    ("quality_score", sa.Numeric(), "0"),
    ("decay_score", sa.Numeric(), "0"),
    ("status", sa.String(length=16), "CANDIDATE"),
    ("last_validated_at", sa.DateTime(timezone=True), None),
    ("updated_at", sa.DateTime(timezone=True), None),
    ("supersedes_rule_id", sa.String(length=64), None),
    ("supersedes_version", sa.Integer(), None),
    ("update_reason", sa.String(length=255), None),
    ("known_at", sa.DateTime(timezone=True), None),
)

_NEW_INDEXES: tuple[tuple[str, list[str]], ...] = (
    ("ix_ai_compressed_experience_account_mode_status", ["account_id", "mode", "status"]),
    ("ix_ai_compressed_experience_experience_type", ["experience_type"]),
    ("ix_ai_compressed_experience_share_scope", ["share_scope"]),
)


def _column_names(inspector, table: str) -> set[str]:
    if table not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _index_names(inspector, table: str) -> set[str]:
    if table not in set(inspector.get_table_names()):
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def _add_v2_columns() -> None:
    for name, column_type, default in _ADDED_COLUMNS:
        op.add_column(
            _CARD_TABLE,
            sa.Column(
                name,
                column_type,
                nullable=default is None,
                server_default=sa.text(f"'{default}'") if default is not None else None,
            ),
        )


def _backfill() -> None:
    op.execute(
        sa.text(
            "UPDATE ai_compressed_experience "
            "SET experience_type='COMPRESSED_EXPERIENCE' "
            "WHERE experience_type IS NULL OR experience_type=''"
        )
    )
    op.execute(
        sa.text(
            "UPDATE ai_compressed_experience SET status='WATCH' "
            "WHERE experience_type='COMPRESSED_EXPERIENCE' "
            "AND update_reason IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE ai_compressed_experience SET known_at=created_at "
            "WHERE known_at IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE ai_compressed_experience SET updated_at=created_at "
            "WHERE updated_at IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE ai_compressed_experience SET share_scope='ACCOUNT_MODE' "
            "WHERE share_scope IS NULL"
        )
    )


def _create_indexes(existing: set[str]) -> None:
    for name, columns in _NEW_INDEXES:
        if name not in existing:
            op.create_index(name, _CARD_TABLE, columns)


def _create_card_version_table() -> None:
    op.create_table(
        "growth_card_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("card_rule_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=True),
        sa.Column("proposal_hash", sa.String(length=64), nullable=False),
        sa.Column("source_episode_ids_json", sa.JSON(), nullable=True),
        sa.Column("trigger_signature_json", sa.JSON(), nullable=True),
        sa.Column("context_signature_json", sa.JSON(), nullable=True),
        sa.Column("support_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "contradiction_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("quality_score", sa.Numeric(), nullable=True),
        sa.Column("decay_score", sa.Numeric(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("update_reason", sa.String(length=255), nullable=True),
        sa.Column("supersedes_rule_id", sa.String(length=64), nullable=True),
        sa.Column("supersedes_version", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "card_rule_id",
            "version",
            "proposal_hash",
            name="uq_growth_card_version_event",
        ),
    )
    op.create_index(
        "ix_growth_card_versions_card_rule_id",
        "growth_card_versions",
        ["card_rule_id"],
    )


def _create_decision_trace_table() -> None:
    op.create_table(
        "growth_card_decision_traces",
        sa.Column("trace_id", sa.String(length=64), primary_key=True),
        sa.Column("decision_id", sa.String(length=64), nullable=True),
        sa.Column("evidence_package_id", sa.String(length=64), nullable=True),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger_signature_json", sa.JSON(), nullable=True),
        sa.Column("context_signature_json", sa.JSON(), nullable=True),
        sa.Column("candidate_card_refs_json", sa.JSON(), nullable=True),
        sa.Column("selected_card_refs_json", sa.JSON(), nullable=True),
        sa.Column("excluded_card_refs_json", sa.JSON(), nullable=True),
        sa.Column("excluded_reasons_json", sa.JSON(), nullable=True),
        sa.Column("card_versions_json", sa.JSON(), nullable=True),
        sa.Column("retrieval_scores_json", sa.JSON(), nullable=True),
        sa.Column("applicability_json", sa.JSON(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filtered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retrieval_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "context_tokens_estimate",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_growth_card_decision_traces_decision_id",
        "growth_card_decision_traces",
        ["decision_id"],
    )


def upgrade() -> None:
    if alembic_context.is_offline_mode():
        _add_v2_columns()
        _backfill()
        _create_indexes(set())
        _create_card_version_table()
        _create_decision_trace_table()
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if _CARD_TABLE in existing_tables:
        present = _column_names(inspector, _CARD_TABLE)
        for name, column_type, default in _ADDED_COLUMNS:
            if name in present:
                continue
            op.add_column(
                _CARD_TABLE,
                sa.Column(
                    name,
                    column_type,
                    nullable=default is None,
                    server_default=(
                        sa.text(f"'{default}'") if default is not None else None
                    ),
                ),
            )
        _backfill()
        _create_indexes(_index_names(inspector, _CARD_TABLE))

    if "growth_card_versions" not in existing_tables:
        _create_card_version_table()
    if "growth_card_decision_traces" not in existing_tables:
        _create_decision_trace_table()


def downgrade() -> None:
    if alembic_context.is_offline_mode():
        op.drop_index(
            "ix_growth_card_decision_traces_decision_id",
            table_name="growth_card_decision_traces",
        )
        op.drop_table("growth_card_decision_traces")
        op.drop_index(
            "ix_growth_card_versions_card_rule_id", table_name="growth_card_versions"
        )
        op.drop_table("growth_card_versions")
        for name, _columns in _NEW_INDEXES:
            op.drop_index(name, table_name=_CARD_TABLE)
        for name, _column_type, _default in reversed(_ADDED_COLUMNS):
            op.drop_column(_CARD_TABLE, name)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "growth_card_decision_traces" in existing_tables:
        if (
            "ix_growth_card_decision_traces_decision_id"
            in _index_names(inspector, "growth_card_decision_traces")
        ):
            op.drop_index(
                "ix_growth_card_decision_traces_decision_id",
                table_name="growth_card_decision_traces",
            )
        op.drop_table("growth_card_decision_traces")
    if "growth_card_versions" in existing_tables:
        if (
            "ix_growth_card_versions_card_rule_id"
            in _index_names(inspector, "growth_card_versions")
        ):
            op.drop_index(
                "ix_growth_card_versions_card_rule_id",
                table_name="growth_card_versions",
            )
        op.drop_table("growth_card_versions")
    if _CARD_TABLE in existing_tables:
        existing_indexes = _index_names(inspector, _CARD_TABLE)
        for name, _columns in _NEW_INDEXES:
            if name in existing_indexes:
                op.drop_index(name, table_name=_CARD_TABLE)
        present = _column_names(inspector, _CARD_TABLE)
        with op.batch_alter_table(_CARD_TABLE) as batch:
            for name, _column_type, _default in reversed(_ADDED_COLUMNS):
                if name in present:
                    batch.drop_column(name)


__all__ = ["down_revision", "downgrade", "revision", "upgrade"]
