"""Full-day opportunity ledger and opportunity-level Top10 identity.

Revision ID: 0032_opportunity_ledger
Revises: 0031_scan_snapshot_labels
"""

import sqlalchemy as sa
from alembic import op

revision = "0032_opportunity_ledger"
down_revision = "0031_scan_snapshot_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scan_snapshots", sa.Column("trading_day", sa.String(10)))
    op.add_column(
        "scan_snapshots",
        sa.Column("snapshot_version", sa.String(16), server_default="scan-snapshot-v1"),
    )
    op.add_column("scan_snapshots", sa.Column("snapshot_hash", sa.String(64)))
    op.create_index("ix_scan_snapshots_trading_day", "scan_snapshots", ["trading_day"])
    op.create_index("ix_scan_snapshots_snapshot_hash", "scan_snapshots", ["snapshot_hash"])
    with op.batch_alter_table("daily_opportunity_top10", recreate="always") as batch:
        batch.drop_constraint("uq_daily_top10_day_symbol", type_="unique")
        batch.add_column(sa.Column("observation_id", sa.String(64)))
        batch.add_column(sa.Column("snapshot_hash", sa.String(64)))
        batch.add_column(
            sa.Column("snapshot_version", sa.String(16), server_default="scan-snapshot-v1")
        )
        batch.add_column(sa.Column("evidence_package_json", sa.JSON()))
        batch.create_unique_constraint(
            "uq_daily_top10_day_observation", ["trading_day", "observation_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("daily_opportunity_top10", recreate="always") as batch:
        batch.drop_constraint("uq_daily_top10_day_observation", type_="unique")
        batch.drop_column("evidence_package_json")
        batch.drop_column("snapshot_version")
        batch.drop_column("snapshot_hash")
        batch.drop_column("observation_id")
        batch.create_unique_constraint("uq_daily_top10_day_symbol", ["trading_day", "symbol"])
    op.drop_index("ix_scan_snapshots_snapshot_hash", table_name="scan_snapshots")
    op.drop_index("ix_scan_snapshots_trading_day", table_name="scan_snapshots")
    op.drop_column("scan_snapshots", "snapshot_hash")
    op.drop_column("scan_snapshots", "snapshot_version")
    op.drop_column("scan_snapshots", "trading_day")
