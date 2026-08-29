"""dynamic OKX instrument registry table (Phase B: all-market data layer)

Revision ID: 0019_okx_instrument_registry
Revises: 0018_trade_episode_lineage
Create Date: 2026-08-29

The registry is the truth source for the dynamic market universe
(OKX_INSTRUMENT_DISCOVERY). Refreshed by the ops script
`python -m crypto_trader.market_registry.refresh` at a bounded cadence -
never by the trading runtime.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_okx_instrument_registry"
down_revision = "0018_trade_episode_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "okx_instruments",
        sa.Column("inst_id", sa.String(64), primary_key=True),
        sa.Column("inst_type", sa.String(16), nullable=False, index=True),
        sa.Column("uly", sa.String(64)),
        sa.Column("inst_family", sa.String(64)),
        sa.Column("base_ccy", sa.String(32)),
        sa.Column("quote_ccy", sa.String(32)),
        sa.Column("settle_ccy", sa.String(32)),
        sa.Column("state", sa.String(16), nullable=False, index=True),
        sa.Column("tick_sz", sa.String(32)),
        sa.Column("lot_sz", sa.String(32)),
        sa.Column("min_sz", sa.String(32)),
        sa.Column("ct_val", sa.String(32)),
        sa.Column("ct_val_ccy", sa.String(32)),
        sa.Column("ct_type", sa.String(16)),
        sa.Column("lever", sa.String(32)),
        sa.Column("exp_time", sa.String(32)),
        sa.Column("list_time", sa.String(32)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("okx_instruments")
