"""Label-v2 alignment policy audit fields for mid-bar decision times.

Additive nullable columns only; label-v1 rows stay untouched.

Revision ID: 0035_ml_label_v2_alignment
Revises: 0034_ml_forward_model21_lineage
"""

import sqlalchemy as sa
from alembic import op

revision = "0035_ml_label_v2_alignment"
down_revision = "0034_ml_forward_model21_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scan_snapshot_labels",
        sa.Column("alignment_policy_version", sa.String(64), nullable=True),
    )
    op.add_column(
        "scan_snapshot_labels",
        sa.Column("raw_t0", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scan_snapshot_labels",
        sa.Column("aligned_bar_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scan_snapshot_labels",
        sa.Column("partial_start_bar", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "scan_snapshot_labels",
        sa.Column("path_quality", sa.String(32), nullable=True),
    )
    op.add_column(
        "scan_snapshot_labels",
        sa.Column("endpoint_quality", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    for col in (
        "endpoint_quality",
        "path_quality",
        "partial_start_bar",
        "aligned_bar_start",
        "raw_t0",
        "alignment_policy_version",
    ):
        op.drop_column("scan_snapshot_labels", col)
