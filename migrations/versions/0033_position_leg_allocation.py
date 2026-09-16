"""Low-Risk V2 durable leg order/fill allocation (HEDGE final closure H2).

Creates two append-only tables binding orders and fills to exactly one leg:
- position_leg_orders: intended new-risk/reduce allocation per client order id;
- position_leg_fills: applied fill ids (unique) so duplicate WS/REST delivery
  cannot double-apply accounting.

Revision ID: 0033_position_leg_allocation
Revises: 0032_position_leg_accounting
"""

import sqlalchemy as sa
from alembic import op

revision = "0033_position_leg_allocation"
down_revision = "0032_position_leg_accounting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_leg_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("leg_id", sa.String(64), nullable=False, index=True),
        sa.Column("client_order_id", sa.String(64), nullable=False, unique=True),
        sa.Column("internal_order_id", sa.String(64), nullable=True),
        sa.Column("trade_plan_id", sa.String(64), nullable=True),
        sa.Column("decision_id", sa.String(64), nullable=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("intended_quantity", sa.String(80), nullable=False),
        sa.Column("reduce_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_action", sa.String(32), nullable=False, server_default=""),
        sa.Column("state", sa.String(16), nullable=False, server_default="INTENDED"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "position_leg_fills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fill_id", sa.String(64), nullable=False, unique=True),
        sa.Column("leg_id", sa.String(64), nullable=False, index=True),
        sa.Column("client_order_id", sa.String(64), nullable=True),
        sa.Column("order_id", sa.String(64), nullable=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("price", sa.String(80), nullable=False),
        sa.Column("quantity", sa.String(80), nullable=False),
        sa.Column("fee", sa.String(80), nullable=False, server_default="0"),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("position_leg_fills")
    op.drop_table("position_leg_orders")
