"""persist immutable ChiefTrader evidence packages

Revision ID: 0038_llm_evidence
Revises: 0037_resolution_context
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_llm_evidence"
down_revision = "0037_resolution_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "llm_decisions" not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns("llm_decisions")}
    if "evidence_package_json" not in existing:
        op.add_column("llm_decisions", sa.Column("evidence_package_json", sa.JSON()))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "llm_decisions" not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns("llm_decisions")}
    if "evidence_package_json" in existing:
        op.drop_column("llm_decisions", "evidence_package_json")
