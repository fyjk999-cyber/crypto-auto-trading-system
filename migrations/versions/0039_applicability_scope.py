"""explicit applicability scope for research/memory/pattern records

Revision ID: 0039_applicability
Revises: 0038_llm_evidence
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039_applicability"
down_revision = "0038_llm_evidence"
branch_labels = None
depends_on = None

_TABLES = {
    "trade_episodes": [
        ("applicability_scope_json", sa.JSON()),
    ],
    "ai_trade_episodes": [
        ("applicability_scope_json", sa.JSON()),
    ],
    "ai_market_patterns": [
        ("symbol", sa.String(length=32)),
        ("applicability_scope_json", sa.JSON()),
    ],
    "ai_compressed_experience": [
        ("symbol", sa.String(length=32)),
        ("applicability_scope_json", sa.JSON()),
    ],
    "research_reports": [
        ("symbol", sa.String(length=32)),
        ("applicability_scope_json", sa.JSON()),
    ],
}
_GLOBAL_SCOPE = '{"scope":"GLOBAL","backfilled":true}'


def _column_names(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table, columns in _TABLES.items():
        if table not in existing_tables:
            continue
        present = _column_names(inspector, table)
        added_scope = False
        for name, column_type in columns:
            if name not in present:
                op.add_column(table, sa.Column(name, column_type))
                if name == "applicability_scope_json":
                    added_scope = True
        if added_scope:
            # Backfill the scope as a bound parameter: the JSON literal
            # contains "true", and an inline SQL text would let SQLAlchemy
            # parse ":true" as a bind parameter (InvalidRequestError).
            op.execute(
                sa.text(
                    f"UPDATE {table} SET applicability_scope_json = :scope "
                    "WHERE applicability_scope_json IS NULL"
                ).bindparams(scope=_GLOBAL_SCOPE)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table, columns in reversed(list(_TABLES.items())):
        if table not in existing_tables:
            continue
        present = _column_names(inspector, table)
        for name, _column_type in reversed(columns):
            if name in present:
                op.drop_column(table, name)
