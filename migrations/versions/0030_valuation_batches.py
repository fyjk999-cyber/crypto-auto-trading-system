"""immutable equity valuation batches

Revision ID: 0030_valuation_batches
Revises: 0029_ledger_account
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_valuation_batches"
down_revision = "0029_ledger_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "valuation_batches" not in tables:
        op.create_table(
            "valuation_batches",
            sa.Column("valuation_id", sa.String(64), primary_key=True),
            sa.Column("account_id", sa.String(64), nullable=False, server_default="default"),
            sa.Column("currency", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("valuation_as_of", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ledger_watermark", sa.String(64), nullable=True),
            sa.Column("position_snapshot_ref", sa.String(64), nullable=True),
            sa.Column("policy_version", sa.String(32), nullable=False, server_default="v1"),
            sa.Column("raw_mtm_equity", sa.String(80), nullable=True),
            sa.Column("available_margin", sa.String(80), nullable=True),
            sa.Column("adjusted_equity", sa.String(80), nullable=True),
            sa.Column("peak_adjusted_equity", sa.String(80), nullable=True),
            sa.Column("drawdown_amount", sa.String(80), nullable=True),
            sa.Column("quality", sa.String(16), nullable=False, server_default="HEALTHY"),
            sa.Column("reason_codes_json", sa.JSON(), nullable=True),
            sa.Column("solvency", sa.String(16), nullable=True),
            sa.Column("missing_marks_json", sa.JSON(), nullable=True),
            sa.Column("stale_marks_json", sa.JSON(), nullable=True),
            sa.Column(
                "allowed_time_skew_seconds", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "actual_skew_seconds", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("components_json", sa.JSON(), nullable=True),
        )
    if "equity_snapshots" in tables:
        columns = {c["name"] for c in inspector.get_columns("equity_snapshots")}
        if "valuation_id" not in columns:
            op.add_column(
                "equity_snapshots",
                sa.Column("valuation_id", sa.String(64), nullable=True),
            )


def downgrade() -> None:
    op.drop_table("valuation_batches")
    op.drop_column("equity_snapshots", "valuation_id")
