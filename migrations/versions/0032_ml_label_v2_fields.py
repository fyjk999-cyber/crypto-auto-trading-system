"""Low-Risk ML label-v2 exact factual fields (M1).

Additive nullable columns on scan_snapshot_labels for exact T0+horizon
reconstruction, alignment/data-gap audit, versioned cost economics and the
usable_for_training gate. label-v1 rows stay untouched and unreadable by the
final scientific path.

Revision ID: 0032_ml_label_v2_fields
Revises: 0031_scan_snapshot_labels
"""

import sqlalchemy as sa
from alembic import op

revision = "0032_ml_label_v2_fields"
down_revision = "0031_scan_snapshot_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scan_snapshot_labels",
        sa.Column("requested_target_ts", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scan_snapshot_labels",
        sa.Column("actual_target_ts", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scan_snapshot_labels", sa.Column("alignment_error_seconds", sa.Float(), nullable=True)
    )
    op.add_column(
        "scan_snapshot_labels", sa.Column("endpoint_policy", sa.String(64), nullable=True)
    )
    op.add_column(
        "scan_snapshot_labels",
        sa.Column("path_start_ts", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scan_snapshot_labels", sa.Column("path_end_ts", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("scan_snapshot_labels", sa.Column("data_gap", sa.Boolean(), nullable=True))
    op.add_column("scan_snapshot_labels", sa.Column("factual_source", sa.String(64), nullable=True))
    op.add_column("scan_snapshot_labels", sa.Column("entry_price", sa.Float(), nullable=True))
    op.add_column("scan_snapshot_labels", sa.Column("cost_version", sa.String(64), nullable=True))
    op.add_column(
        "scan_snapshot_labels", sa.Column("cost_components_json", sa.JSON(), nullable=True)
    )
    op.add_column(
        "scan_snapshot_labels", sa.Column("maturation_status", sa.String(32), nullable=True)
    )
    op.add_column(
        "scan_snapshot_labels", sa.Column("usable_for_training", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "scan_snapshot_labels", sa.Column("label_config_version", sa.String(64), nullable=True)
    )


def downgrade() -> None:
    for col in (
        "label_config_version",
        "usable_for_training",
        "maturation_status",
        "cost_components_json",
        "cost_version",
        "entry_price",
        "factual_source",
        "data_gap",
        "path_end_ts",
        "path_start_ts",
        "endpoint_policy",
        "alignment_error_seconds",
        "actual_target_ts",
        "requested_target_ts",
    ):
        op.drop_column("scan_snapshot_labels", col)
