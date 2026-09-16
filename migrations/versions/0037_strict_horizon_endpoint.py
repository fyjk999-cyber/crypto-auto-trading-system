"""Strict closed-bar horizon endpoint provenance.

Revision ID: 0037_strict_horizon_endpoint
Revises: 0036_growth_pattern_profile
"""

import sqlalchemy as sa
from alembic import op

revision = "0037_strict_horizon_endpoint"
down_revision = "0036_growth_pattern_profile"
branch_labels = None
depends_on = None

COLUMNS = (
    ("endpoint_policy", sa.String(40)),
    ("final_bar_partial", sa.Boolean()),
    ("data_gap", sa.Boolean()),
    ("pages_fetched", sa.Integer()),
)


def upgrade() -> None:
    for name, column_type in COLUMNS:
        op.add_column(
            "opportunity_outcome_maturations",
            sa.Column(name, column_type, server_default="0" if name != "endpoint_policy" else None),
        )
    op.execute(
        "UPDATE opportunity_outcome_maturations SET endpoint_policy = 'CLOSED_BAR_END_LE_TARGET'"
    )


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("opportunity_outcome_maturations", name)
