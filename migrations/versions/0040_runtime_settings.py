"""Runtime settings: operator-controlled overrides (LLM model selection)

Adds ``runtime_settings`` (key/value, non-secret) so an operator can switch
the ChiefTrader LLM model from the frontend and have the choice survive a
restart. Purely operational: it changes no decision authority, Risk or
Execution behaviour.

Revision ID: 0040_runtime_settings
Revises: 0039_applicability
"""
import sqlalchemy as sa
from alembic import op

revision = "0040_runtime_settings"
down_revision = "0039_applicability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("runtime_settings")
