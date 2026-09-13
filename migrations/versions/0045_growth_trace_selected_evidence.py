"""trace selected evidence domain provenance

Revision ID: 0045_growth_trace_selected_evidence
Revises: 0044_growth_review_attempt_bindings
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_growth_trace_selected_evidence"
down_revision = "0044_growth_review_attempt_bindings"
branch_labels = None
depends_on = None
TABLE = "growth_card_decision_traces"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns(TABLE)}
    if "selected_evidence_json" not in columns:
        op.add_column(
            TABLE,
            sa.Column("selected_evidence_json", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns(TABLE)}
    if "selected_evidence_json" in columns:
        op.drop_column(TABLE, "selected_evidence_json")
