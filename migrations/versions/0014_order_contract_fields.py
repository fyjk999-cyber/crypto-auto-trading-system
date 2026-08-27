"""add market_type / position_side / reduce_only to orders

Revision ID: 0014_order_contract
Revises: 0013_factor_v10
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_order_contract"
down_revision = "0014_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("market_type", sa.String(length=16), nullable=False, server_default="SPOT"),
    )
    op.add_column(
        "orders",
        sa.Column("position_side", sa.String(length=8), nullable=False, server_default="FLAT"),
    )
    op.add_column(
        "orders",
        sa.Column("reduce_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("orders", "reduce_only")
    op.drop_column("orders", "position_side")
    op.drop_column("orders", "market_type")
