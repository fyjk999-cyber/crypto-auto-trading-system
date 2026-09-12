"""Growth review attempt immutable job-binding association.

Revision ID: 0044_growth_review_attempt_bindings
Revises: 0043_growth_review_job_binding
Create Date: 2026-09-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044_growth_review_attempt_bindings"
down_revision = "0043_growth_review_job_binding"
branch_labels = None
depends_on = None

TABLE = "growth_review_attempt_bindings"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE in inspector.get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("job_key", sa.String(length=128), nullable=False),
        sa.Column("job_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "attempt_id",
            "job_key",
            "job_revision",
            name="uq_growth_review_attempt_binding",
        ),
    )
    op.create_index(
        "ix_growth_review_attempt_bindings_attempt_id",
        TABLE,
        ["attempt_id"],
    )
    op.create_index(
        "ix_growth_review_attempt_bindings_job_key",
        TABLE,
        ["job_key"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    op.drop_table(TABLE)
