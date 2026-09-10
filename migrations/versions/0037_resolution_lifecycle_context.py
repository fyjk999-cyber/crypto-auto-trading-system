"""funding event resolution lifecycle context

Revision ID: 0037_resolution_context
Revises: 0036_funding_resolution
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_resolution_context"
down_revision = "0036_funding_resolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "funding_event_resolutions" in inspector.get_table_names():
        columns = {
            column["name"]
            for column in inspector.get_columns("funding_event_resolutions")
        }
        if "trade_plan_id" not in columns:
            op.add_column(
                "funding_event_resolutions",
                sa.Column("trade_plan_id", sa.String(64), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "funding_event_resolutions" in inspector.get_table_names():
        columns = {
            column["name"]
            for column in inspector.get_columns("funding_event_resolutions")
        }
        if "trade_plan_id" in columns:
            with op.batch_alter_table("funding_event_resolutions") as batch_op:
                batch_op.drop_column("trade_plan_id")
