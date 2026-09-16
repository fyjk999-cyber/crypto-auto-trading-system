"""ML dataset collector: scan snapshots + control samples (Phase B).

Revision ID: 0029_scan_snapshots
Revises: 0028_opportunity_outcomes
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_scan_snapshots"
down_revision = "0028_opportunity_outcomes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cycle_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("candidate", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("control", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scanner_rank", sa.Integer()),
        sa.Column("scanner_score", sa.Float()),
        sa.Column("selection_reason", sa.String(200), server_default=""),
        sa.Column("sampling_method", sa.String(40), server_default=""),
        sa.Column("selection_probability", sa.Float()),
        sa.Column("market_regime", sa.String(32)),
        sa.Column("features_json", sa.JSON()),
        sa.Column("outcome_status", sa.String(16), server_default="PENDING"),
        sa.Column("authority", sa.String(24), server_default="LEARNING_ONLY"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("snapshot_id", name="uq_scan_snapshots_snapshot_id"),
    )
    op.create_index("ix_scan_snapshots_captured_at", "scan_snapshots", ["captured_at"])
    op.create_index("ix_scan_snapshots_cycle_id", "scan_snapshots", ["cycle_id"])
    op.create_index("ix_scan_snapshots_symbol", "scan_snapshots", ["symbol"])
    op.create_index("ix_scan_snapshots_outcome_status", "scan_snapshots", ["outcome_status"])


def downgrade() -> None:
    op.drop_index("ix_scan_snapshots_outcome_status", table_name="scan_snapshots")
    op.drop_index("ix_scan_snapshots_symbol", table_name="scan_snapshots")
    op.drop_index("ix_scan_snapshots_cycle_id", table_name="scan_snapshots")
    op.drop_index("ix_scan_snapshots_captured_at", table_name="scan_snapshots")
    op.drop_table("scan_snapshots")
