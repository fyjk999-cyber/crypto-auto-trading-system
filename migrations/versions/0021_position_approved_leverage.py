"""persist approved leverage on factual position projections

Revision ID: 0021_position_leverage
Revises: 0020_episode_exit_lineage
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from crypto_trader.persistence.models import ExactDecimal

revision = "0021_position_leverage"
down_revision = "0020_episode_exit_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "positions_projection",
        sa.Column("leverage", ExactDecimal(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("positions_projection", "leverage")
