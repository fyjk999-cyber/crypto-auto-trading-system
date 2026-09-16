"""Immutable Growth memory versions for as-of retrieval.

Revision ID: 0040_growth_memory_versions
Revises: 0039_generalized_knowledge
"""

import sqlalchemy as sa
from alembic import op

revision = "0040_growth_memory_versions"
down_revision = "0039_generalized_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "growth_memory_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("object_type", sa.String(40), nullable=False),
        sa.Column("object_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer()),
        sa.Column("sample_tier", sa.String(32)),
        sa.Column("memory_speed", sa.String(32)),
        sa.Column("quality", sa.Float()),
        sa.Column("contradictions", sa.Integer()),
        sa.Column("post_cost_expectancy_bps", sa.Float()),
        sa.Column("payload_json", sa.JSON()),
        sa.Column("source_refs_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("object_type", "object_id", "version", name="uq_growth_memory_version"),
    )
    op.create_index(
        "ix_growth_memory_versions_object_type", "growth_memory_versions", ["object_type"]
    )
    op.create_index("ix_growth_memory_versions_object_id", "growth_memory_versions", ["object_id"])
    op.create_index(
        "ix_growth_memory_versions_available_at", "growth_memory_versions", ["available_at"]
    )


def downgrade() -> None:
    for name in (
        "ix_growth_memory_versions_available_at",
        "ix_growth_memory_versions_object_id",
        "ix_growth_memory_versions_object_type",
    ):
        op.drop_index(name, table_name="growth_memory_versions")
    op.drop_table("growth_memory_versions")
