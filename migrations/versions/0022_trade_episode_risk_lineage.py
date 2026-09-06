"""add explainable risk lineage to factual trade episodes

Revision ID: 0022_episode_risk_lineage
Revises: 0021_position_leverage
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_episode_risk_lineage"
down_revision = "0021_position_leverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trade_episodes",
        sa.Column("risk_decision_ids_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trade_episodes", "risk_decision_ids_json")
