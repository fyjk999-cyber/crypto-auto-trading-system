"""funding coverage events + per-event resolution provenance

Revision ID: 0036_funding_resolution
Revises: 0035_review_claim
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_funding_resolution"
down_revision = "0035_review_claim"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "funding_coverage_windows" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("funding_coverage_windows")
        }
        if "events_json" not in columns:
            op.add_column(
                "funding_coverage_windows", sa.Column("events_json", sa.JSON(), nullable=True)
            )
    if "funding_event_resolutions" not in tables:
        op.create_table(
            "funding_event_resolutions",
            sa.Column("resolution_id", sa.String(64), primary_key=True),
            sa.Column("account_id", sa.String(64), nullable=False),
            sa.Column("instrument_id", sa.String(64), nullable=False),
            sa.Column("currency", sa.String(16), nullable=False, server_default="USDT"),
            sa.Column("settlement_timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="UNPROVEN"),
            sa.Column("quantity", sa.String(80), nullable=True),
            sa.Column("mark_price", sa.String(80), nullable=True),
            sa.Column("funding_rate", sa.String(80), nullable=True),
            sa.Column("ledger_transaction_id", sa.String(64), nullable=True),
            sa.Column("reason", sa.String(128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "account_id",
                "instrument_id",
                "settlement_timestamp",
                name="uq_funding_event_resolution",
            ),
        )
        op.create_index(
            "ix_funding_event_resolutions_account_id",
            "funding_event_resolutions",
            ["account_id"],
        )
        op.create_index(
            "ix_funding_event_resolutions_instrument_id",
            "funding_event_resolutions",
            ["instrument_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "funding_event_resolutions" in tables:
        op.drop_table("funding_event_resolutions")
    if "funding_coverage_windows" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("funding_coverage_windows")
        }
        if "events_json" in columns:
            op.drop_column("funding_coverage_windows", "events_json")
