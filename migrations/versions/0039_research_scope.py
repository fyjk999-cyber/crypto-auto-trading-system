"""add explicit applicability scope to stored research

Revision ID: 0039_research_scope
Revises: 0038_llm_evidence
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039_research_scope"
down_revision = "0038_llm_evidence"
branch_labels = None
depends_on = None


def _indexes(inspector) -> set[str]:
    return {item["name"] for item in inspector.get_indexes("research_reports")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "research_reports" not in set(inspector.get_table_names()):
        return

    existing = {column["name"] for column in inspector.get_columns("research_reports")}
    if "scope_type" not in existing:
        op.add_column(
            "research_reports",
            sa.Column(
                "scope_type",
                sa.String(length=24),
                nullable=False,
                server_default="GLOBAL",
            ),
        )
    if "symbol" not in existing:
        op.add_column(
            "research_reports",
            sa.Column("symbol", sa.String(length=32), nullable=True),
        )
    if "regime" not in existing:
        op.add_column(
            "research_reports",
            sa.Column("regime", sa.String(length=32), nullable=True),
        )

    inspector = sa.inspect(bind)
    indexes = _indexes(inspector)
    if "ix_research_reports_scope_type" not in indexes:
        op.create_index(
            "ix_research_reports_scope_type",
            "research_reports",
            ["scope_type"],
            unique=False,
        )
    if "ix_research_reports_symbol" not in indexes:
        op.create_index(
            "ix_research_reports_symbol",
            "research_reports",
            ["symbol"],
            unique=False,
        )
    if "ix_research_reports_regime" not in indexes:
        op.create_index(
            "ix_research_reports_regime",
            "research_reports",
            ["regime"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "research_reports" not in set(inspector.get_table_names()):
        return

    indexes = _indexes(inspector)
    for name in (
        "ix_research_reports_regime",
        "ix_research_reports_symbol",
        "ix_research_reports_scope_type",
    ):
        if name in indexes:
            op.drop_index(name, table_name="research_reports")

    existing = {column["name"] for column in sa.inspect(bind).get_columns("research_reports")}
    for name in ("regime", "symbol", "scope_type"):
        if name in existing:
            op.drop_column("research_reports", name)
