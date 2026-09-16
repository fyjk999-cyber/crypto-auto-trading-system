"""Low-Risk V2 leg accounting fields (HEDGE final closure H1).

Adds per-leg VWAP/PnL/fees/funding/terminal-reason and a bounded applied-fill
id list so fills are applied exactly once. Additive and nullable.

Revision ID: 0032_position_leg_accounting
Revises: 0031_scan_snapshot_labels
"""

import sqlalchemy as sa
from alembic import op

revision = "0032_position_leg_accounting"
down_revision = "0031_scan_snapshot_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("position_legs", sa.Column("average_entry_price", sa.String(80), nullable=True))
    op.add_column("position_legs", sa.Column("closed_quantity", sa.String(80), nullable=True))
    op.add_column("position_legs", sa.Column("realized_pnl", sa.String(80), nullable=True))
    op.add_column("position_legs", sa.Column("unrealized_pnl", sa.String(80), nullable=True))
    op.add_column("position_legs", sa.Column("fees", sa.String(80), nullable=True))
    op.add_column("position_legs", sa.Column("funding", sa.String(80), nullable=True))
    op.add_column("position_legs", sa.Column("terminal_reason", sa.String(64), nullable=True))
    op.add_column("position_legs", sa.Column("applied_fill_ids_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("position_legs", "applied_fill_ids_json")
    op.drop_column("position_legs", "terminal_reason")
    op.drop_column("position_legs", "funding")
    op.drop_column("position_legs", "fees")
    op.drop_column("position_legs", "unrealized_pnl")
    op.drop_column("position_legs", "realized_pnl")
    op.drop_column("position_legs", "closed_quantity")
    op.drop_column("position_legs", "average_entry_price")
