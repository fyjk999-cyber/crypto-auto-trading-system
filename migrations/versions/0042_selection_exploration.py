"""ChiefTrader directory exploration lineage on market selections.

Adds ``exploration_rounds`` and ``directory_query_json`` so a persisted
selection can answer:

    was this symbol supplied in the initial pool,
    or did the ChiefTrader actively discover it via bounded directory
    exploration?

Both columns are research-attention lineage only; no direction, order or
authority is added.

Revision ID: 0042_selection_exploration
Revises: 0041_market_selection
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042_selection_exploration"
down_revision = "0041_market_selection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "market_selections" not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns("market_selections")}
    if "exploration_rounds" not in existing:
        op.add_column(
            "market_selections", sa.Column("exploration_rounds", sa.Integer(), nullable=True)
        )
    if "directory_query_json" not in existing:
        op.add_column(
            "market_selections", sa.Column("directory_query_json", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "market_selections" not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns("market_selections")}
    if "directory_query_json" in existing:
        op.drop_column("market_selections", "directory_query_json")
    if "exploration_rounds" in existing:
        op.drop_column("market_selections", "exploration_rounds")
