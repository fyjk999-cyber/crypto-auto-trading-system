"""bind structured-review attempts to exact growth job revision

Revision ID: 0043_growth_review_job_binding
Revises: 0042_growth_v2_cards
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context as alembic_context
from alembic import op

revision = "0043_growth_review_job_binding"
down_revision = "0042_growth_v2_cards"
branch_labels = None
depends_on = None

_TABLE = "growth_review_attempts"


def _columns(inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns(_TABLE)}


_OLD_UNIQUE = "uq_growth_review_attempt"
_NEW_UNIQUE = "uq_growth_review_attempt_scope"
_SCOPE_COLUMNS = [
    "review_date",
    "episode_id",
    "profile_version",
    "account_id",
    "mode",
    "input_hash",
    "job_key",
    "job_revision",
    "attempt_no",
]


def _migrate_unique_constraint(inspector) -> None:
    if "sqlite" in op.get_bind().dialect.name:
        with op.batch_alter_table(_TABLE, recreate="always") as batch:
            names = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(_TABLE)
            }
            if _OLD_UNIQUE in names:
                batch.drop_constraint(_OLD_UNIQUE, type_="unique")
            if _NEW_UNIQUE not in names:
                batch.create_unique_constraint(_NEW_UNIQUE, _SCOPE_COLUMNS)
        return
    names = {constraint["name"] for constraint in inspector.get_unique_constraints(_TABLE)}
    if _OLD_UNIQUE in names:
        op.drop_constraint(_OLD_UNIQUE, _TABLE, type_="unique")
    if _NEW_UNIQUE not in names:
        op.create_unique_constraint(_NEW_UNIQUE, _TABLE, _SCOPE_COLUMNS)


def upgrade() -> None:
    if alembic_context.is_offline_mode():
        op.add_column(_TABLE, sa.Column("job_key", sa.String(length=128), nullable=True))
        op.add_column(_TABLE, sa.Column("job_revision", sa.Integer(), nullable=True))
        op.create_index("ix_growth_review_attempts_job_key", _TABLE, ["job_key"])
        op.create_index(
            "ix_growth_review_attempts_job_revision", _TABLE, ["job_revision"]
        )
        op.drop_constraint(_OLD_UNIQUE, _TABLE, type_="unique")
        op.create_unique_constraint(_NEW_UNIQUE, _TABLE, _SCOPE_COLUMNS)
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in set(inspector.get_table_names()):
        return
    present = _columns(inspector)
    if "job_key" not in present:
        op.add_column(_TABLE, sa.Column("job_key", sa.String(length=128), nullable=True))
    if "job_revision" not in present:
        op.add_column(_TABLE, sa.Column("job_revision", sa.Integer(), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes(_TABLE)}
    if "ix_growth_review_attempts_job_key" not in indexes:
        op.create_index("ix_growth_review_attempts_job_key", _TABLE, ["job_key"])
    if "ix_growth_review_attempts_job_revision" not in indexes:
        op.create_index(
            "ix_growth_review_attempts_job_revision", _TABLE, ["job_revision"]
        )
    _migrate_unique_constraint(inspector)


def downgrade() -> None:
    if alembic_context.is_offline_mode():
        op.drop_index(
            "ix_growth_review_attempts_job_revision", table_name=_TABLE
        )
        op.drop_index("ix_growth_review_attempts_job_key", table_name=_TABLE)
        op.drop_column(_TABLE, "job_revision")
        op.drop_column(_TABLE, "job_key")
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in set(inspector.get_table_names()):
        return
    indexes = {index["name"] for index in inspector.get_indexes(_TABLE)}
    if "ix_growth_review_attempts_job_revision" in indexes:
        op.drop_index(
            "ix_growth_review_attempts_job_revision", table_name=_TABLE
        )
    if "ix_growth_review_attempts_job_key" in indexes:
        op.drop_index("ix_growth_review_attempts_job_key", table_name=_TABLE)
    names = {
        constraint["name"] for constraint in inspector.get_unique_constraints(_TABLE)
    }
    if "sqlite" in bind.dialect.name:
        with op.batch_alter_table(_TABLE, recreate="always") as batch:
            if _NEW_UNIQUE in names:
                batch.drop_constraint(_NEW_UNIQUE, type_="unique")
            if _OLD_UNIQUE not in names:
                batch.create_unique_constraint(
                    _OLD_UNIQUE,
                    [
                        "review_date",
                        "episode_id",
                        "profile_version",
                        "input_hash",
                        "attempt_no",
                    ],
                )
    else:
        if _NEW_UNIQUE in names:
            op.drop_constraint(_NEW_UNIQUE, _TABLE, type_="unique")
        if _OLD_UNIQUE not in names:
            op.create_unique_constraint(
                _OLD_UNIQUE,
                _TABLE,
                [
                    "review_date",
                    "episode_id",
                    "profile_version",
                    "input_hash",
                    "attempt_no",
                ],
            )
    present = _columns(inspector)
    if "job_revision" in present:
        op.drop_column(_TABLE, "job_revision")
    if "job_key" in present:
        op.drop_column(_TABLE, "job_key")


__all__ = ["down_revision", "downgrade", "revision", "upgrade"]
