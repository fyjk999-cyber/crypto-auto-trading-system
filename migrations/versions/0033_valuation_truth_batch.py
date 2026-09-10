"""valuation truth batch fields + nullable unavailable equity

Revision ID: 0033_valuation_truth
Revises: 0032_ledger_ownership
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_valuation_truth"
down_revision = "0032_ledger_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "valuation_batches" in tables:
        columns = {column["name"] for column in inspector.get_columns("valuation_batches")}
        if "drawdown_ratio" not in columns:
            op.add_column(
                "valuation_batches",
                sa.Column("drawdown_ratio", sa.String(80), nullable=True),
            )
        if "market_as_of" not in columns:
            op.add_column(
                "valuation_batches",
                sa.Column("market_as_of", sa.DateTime(timezone=True), nullable=True),
            )

    if "equity_snapshots" in tables:
        nullable_now = {
            "cash_flow_adjusted_equity",
            "peak_equity",
            "peak_adjusted_equity",
            "drawdown",
        }
        alter = {
            column["name"]
            for column in inspector.get_columns("equity_snapshots")
            if column["name"] in nullable_now and not column["nullable"]
        }
        if alter:
            with op.batch_alter_table("equity_snapshots") as batch:
                for name in sorted(alter):
                    batch.alter_column(
                        name,
                        existing_type=sa.String(80),
                        nullable=True,
                    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "equity_snapshots" in tables:
        columns = {column["name"] for column in inspector.get_columns("equity_snapshots")}
        not_nullable = {
            "cash_flow_adjusted_equity",
            "peak_equity",
            "peak_adjusted_equity",
            "drawdown",
        }
        alter = columns & not_nullable
        if alter:
            with op.batch_alter_table("equity_snapshots") as batch:
                for name in sorted(alter):
                    batch.alter_column(
                        name,
                        existing_type=sa.String(80),
                        nullable=False,
                        server_default="0",
                    )
    if "valuation_batches" in tables:
        columns = {column["name"] for column in inspector.get_columns("valuation_batches")}
        if "market_as_of" in columns:
            op.drop_column("valuation_batches", "market_as_of")
        if "drawdown_ratio" in columns:
            op.drop_column("valuation_batches", "drawdown_ratio")
