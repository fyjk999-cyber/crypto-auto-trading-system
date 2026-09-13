"""durable fill settlement state

A durable FillORM is not proof that the fill is settled: the ledger posting, the
portfolio projection and the TradePlan convergence all happen downstream and can
be interrupted. This table records per-fill settlement progress so an
interrupted settlement can be completed after an event failure, a crash, a
replay or a restart - without duplicating ledger, fee, position or episodes.

Revision ID: 0048_fill_settlements
Revises: 0047_shadow_learning
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0048_fill_settlements"
down_revision = "0047_shadow_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fill_settlements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fill_id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_type", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("ledger_transaction_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["fill_id"], ["fills.fill_id"]),
        sa.UniqueConstraint("fill_id", name="uq_fill_settlements_fill_id"),
    )
    op.create_index(
        "ix_fill_settlements_fill_id", "fill_settlements", ["fill_id"]
    )
    op.create_index("ix_fill_settlements_order_id", "fill_settlements", ["order_id"])
    op.create_index("ix_fill_settlements_symbol", "fill_settlements", ["symbol"])
    # §4: historical fills are NOT assumed settled. A fill WITH a ledger posting
    # is ACCOUNTED (still needs a lifecycle convergence pass); a fill WITHOUT one
    # is PENDING. Either way it is picked up by startup recovery.
    op.execute(
        """
        INSERT INTO fill_settlements
            (fill_id, order_id, symbol, state, attempt_count, created_at, updated_at)
        SELECT f.fill_id, f.order_id, f.symbol,
               CASE WHEN EXISTS (
                   SELECT 1 FROM ledger_transactions t WHERE t.fill_id = f.fill_id
               ) THEN 'ACCOUNTED' ELSE 'PENDING' END,
               0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM fills f
        """
    )


def downgrade() -> None:
    op.drop_index("ix_fill_settlements_symbol", table_name="fill_settlements")
    op.drop_index("ix_fill_settlements_order_id", table_name="fill_settlements")
    op.drop_index("ix_fill_settlements_fill_id", table_name="fill_settlements")
    op.drop_table("fill_settlements")
