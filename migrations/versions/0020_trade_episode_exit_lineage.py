"""add factual exit decision lineage to trade episodes

Revision ID: 0020_episode_exit_lineage
Revises: 0019_llm_decision_reasons
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_episode_exit_lineage"
down_revision = "0019_llm_decision_reasons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trade_episodes",
        sa.Column("exit_decision_id", sa.String(64), nullable=True),
    )
    op.execute(
        """
        UPDATE trade_episodes
        SET exit_decision_id = (
            SELECT trade_plans.exit_decision_id
            FROM trade_plans
            WHERE trade_plans.trade_plan_id = trade_episodes.trade_plan_id
        )
        """
    )
    op.create_index(
        "ix_trade_episodes_exit_decision_id",
        "trade_episodes",
        ["exit_decision_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trade_episodes_exit_decision_id",
        table_name="trade_episodes",
    )
    op.drop_column("trade_episodes", "exit_decision_id")
