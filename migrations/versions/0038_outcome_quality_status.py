"""Maturation quality status and retry metadata.

Revision ID: 0038_outcome_quality_status
Revises: 0037_strict_horizon_endpoint
"""

import sqlalchemy as sa
from alembic import op

revision = "0038_outcome_quality_status"
down_revision = "0037_strict_horizon_endpoint"
branch_labels = None
depends_on = None

COLUMNS = (
    ("maturation_status", sa.String(32)),
    ("usable_for_learning", sa.Boolean()),
    ("quality_reason", sa.String(64)),
    ("attempts", sa.Integer()),
    ("last_attempt_at", sa.DateTime(timezone=True)),
    ("last_error", sa.String(200)),
)


def upgrade() -> None:
    for name, column_type in COLUMNS:
        op.add_column(
            "opportunity_outcome_maturations", sa.Column(name, column_type)
        )


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("opportunity_outcome_maturations", name)
