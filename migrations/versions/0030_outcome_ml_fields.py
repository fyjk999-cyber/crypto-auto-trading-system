"""Phase C ML label fields on opportunity_outcomes.

Revision ID: 0030_outcome_ml_fields
Revises: 0029_scan_snapshots
"""

import sqlalchemy as sa
from alembic import op

revision = "0030_outcome_ml_fields"
down_revision = "0029_scan_snapshots"
branch_labels = None
depends_on = None

COLUMNS = (
    ("future_high", sa.Float()),
    ("future_low", sa.Float()),
    ("realized_volatility", sa.Float()),
    ("long_gross_bps", sa.Float()),
    ("short_gross_bps", sa.Float()),
    ("long_net_bps", sa.Float()),
    ("short_net_bps", sa.Float()),
    ("all_in_cost_bps", sa.Float()),
    ("net_edge_bps", sa.Float()),
    ("min_edge_bps", sa.Float()),
)


def upgrade() -> None:
    for name, column_type in COLUMNS:
        op.add_column(
            "opportunity_outcomes", sa.Column(name, column_type, server_default="0")
        )
    op.add_column(
        "opportunity_outcomes",
        sa.Column("net_edge_label", sa.String(16), server_default="NOT_PROFITABLE"),
    )


def downgrade() -> None:
    op.drop_column("opportunity_outcomes", "net_edge_label")
    for name, _ in reversed(COLUMNS):
        op.drop_column("opportunity_outcomes", name)
