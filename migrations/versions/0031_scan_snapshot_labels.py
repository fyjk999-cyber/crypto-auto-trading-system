"""Factual maturity-gated labels for scan snapshots.

Revision ID: 0031_scan_snapshot_labels
Revises: 0030_outcome_ml_fields
"""

import sqlalchemy as sa
from alembic import op

revision = "0031_scan_snapshot_labels"
down_revision = "0030_outcome_ml_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_snapshot_labels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("snapshot_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon", sa.String(8), nullable=False),
        sa.Column("feature_version", sa.String(32), server_default="scan-features-v1"),
        sa.Column("label_version", sa.String(32), server_default="label-v1"),
        sa.Column("future_high", sa.Float()),
        sa.Column("future_low", sa.Float()),
        sa.Column("realized_volatility", sa.Float()),
        sa.Column("long_gross_bps", sa.Float()),
        sa.Column("short_gross_bps", sa.Float()),
        sa.Column("all_in_cost_bps", sa.Float()),
        sa.Column("long_net_bps", sa.Float()),
        sa.Column("short_net_bps", sa.Float()),
        sa.Column("long_net_edge_bps", sa.Float()),
        sa.Column("short_net_edge_bps", sa.Float()),
        sa.Column("long_label", sa.String(16), server_default="NOT_PROFITABLE"),
        sa.Column("short_label", sa.String(16), server_default="NOT_PROFITABLE"),
        sa.Column("matured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("authority", sa.String(24), server_default="LEARNING_ONLY"),
        sa.UniqueConstraint(
            "snapshot_id",
            "horizon",
            "label_version",
            name="uq_scan_snapshot_labels_identity",
        ),
    )
    op.create_index("ix_scan_snapshot_labels_snapshot_id", "scan_snapshot_labels", ["snapshot_id"])
    op.create_index("ix_scan_snapshot_labels_symbol", "scan_snapshot_labels", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_scan_snapshot_labels_symbol", table_name="scan_snapshot_labels")
    op.drop_index("ix_scan_snapshot_labels_snapshot_id", table_name="scan_snapshot_labels")
    op.drop_table("scan_snapshot_labels")
