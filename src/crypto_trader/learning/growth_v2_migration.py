"""I01 support helper for isolated V2 card-schema unit tests.

The production migration truth is the real Alembic revision
``0040_growth_v2_cards`` (``migrations/versions/0040_growth_v2_cards.py``).
This module remains only as a **test/support** helper so isolated unit tests
can create the extended canonical columns without running the full migration
chain.  It must not be used as an alternative production migration path.

* fresh database: the ORM ``create_all`` path already includes the columns;
* upgrade from an older schema: additive ``ALTER TABLE ... ADD COLUMN``;
* repeat upgrade: idempotent, existing data untouched;
* downgrade / re-upgrade: drops only V2 journals and the columns this helper
  added.

No production database is touched by this module; the test conftest refuses
known runtime/production paths.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from crypto_trader.learning.growth_models import (
    GROWTH_TABLES,
    GrowthBase,
    GrowthCardDecisionTraceORM,
    GrowthCardVersionORM,
    utcnow,
)

EXPERIENCE_CARD_SCHEMA_VERSION = "growth_card_v2"

# name -> DDL type used only when the column is missing.
CARD_COLUMN_PLAN: tuple[tuple[str, str], ...] = (
    ("experience_type", "VARCHAR(32) DEFAULT 'COMPRESSED_EXPERIENCE'"),
    ("account_id", "VARCHAR(64) DEFAULT 'default'"),
    ("mode", "VARCHAR(16) DEFAULT 'PAPER'"),
    ("share_scope", "VARCHAR(32) DEFAULT 'ACCOUNT_MODE'"),
    ("trigger_signature_json", "TEXT"),
    ("context_signature_json", "TEXT"),
    ("factor_refs_json", "TEXT"),
    ("guidance_json", "TEXT"),
    ("source_episode_ids_json", "TEXT"),
    ("supporting_episode_ids_json", "TEXT"),
    ("contradicting_episode_ids_json", "TEXT"),
    ("support_count", "INTEGER DEFAULT 0"),
    ("contradiction_count", "INTEGER DEFAULT 0"),
    ("confidence", "VARCHAR(64) DEFAULT '0'"),
    ("quality_score", "VARCHAR(64) DEFAULT '0'"),
    ("decay_score", "VARCHAR(64) DEFAULT '0'"),
    ("status", "VARCHAR(16) DEFAULT 'CANDIDATE'"),
    ("last_validated_at", "DATETIME"),
    ("updated_at", "DATETIME"),
    ("supersedes_rule_id", "VARCHAR(64)"),
    ("supersedes_version", "INTEGER"),
    ("update_reason", "VARCHAR(255)"),
    ("known_at", "DATETIME"),
)

CARD_TABLE = "ai_compressed_experience"
JOURNAL_TABLES = (GrowthCardVersionORM, GrowthCardDecisionTraceORM)


def _sync_upgrade(connection) -> dict[str, int]:
    inspector = inspect(connection)
    if CARD_TABLE not in inspector.get_table_names():
        raise RuntimeError(
            f"{CARD_TABLE} is absent; apply the base schema before the V2 card upgrade"
        )
    existing = {column["name"] for column in inspector.get_columns(CARD_TABLE)}
    added = 0
    for name, ddl_type in CARD_COLUMN_PLAN:
        if name in existing:
            continue
        connection.execute(
            text(f"ALTER TABLE {CARD_TABLE} ADD COLUMN {name} {ddl_type}")
        )
        added += 1
    # Backfill only rows that predate V2; never overwrite an existing card.
    connection.execute(
        text(
            f"UPDATE {CARD_TABLE} SET experience_type='COMPRESSED_EXPERIENCE' "
            "WHERE experience_type IS NULL"
        )
    )
    connection.execute(
        text(f"UPDATE {CARD_TABLE} SET account_id='default' WHERE account_id IS NULL")
    )
    connection.execute(text(f"UPDATE {CARD_TABLE} SET mode='PAPER' WHERE mode IS NULL"))
    connection.execute(
        text(
            f"UPDATE {CARD_TABLE} SET share_scope='ACCOUNT_MODE' "
            "WHERE share_scope IS NULL"
        )
    )
    connection.execute(
        text(f"UPDATE {CARD_TABLE} SET status='WATCH' WHERE status IS NULL")
    )
    # Pre-V2 compressed-experience rows have no trigger/context; they become
    # WATCH general fallback, never silently ACTIVE.
    connection.execute(
        text(
            f"UPDATE {CARD_TABLE} SET status='WATCH' "
            "WHERE experience_type='COMPRESSED_EXPERIENCE' AND update_reason IS NULL"
        )
    )
    connection.execute(
        text(f"UPDATE {CARD_TABLE} SET confidence='0' WHERE confidence IS NULL")
    )
    connection.execute(
        text(f"UPDATE {CARD_TABLE} SET quality_score='0' WHERE quality_score IS NULL")
    )
    connection.execute(
        text(f"UPDATE {CARD_TABLE} SET decay_score='0' WHERE decay_score IS NULL")
    )
    connection.execute(
        text(
            f"UPDATE {CARD_TABLE} SET updated_at=created_at WHERE updated_at IS NULL"
        )
    )
    connection.execute(
        text(f"UPDATE {CARD_TABLE} SET known_at=created_at WHERE known_at IS NULL")
    )
    # Create the narrow lineage/trace journals if this is an upgrade from v1.
    GrowthBase.metadata.create_all(
        connection, tables=[table.__table__ for table in JOURNAL_TABLES]
    )
    return {"columns_added": added, "schema_version": EXPERIENCE_CARD_SCHEMA_VERSION}


async def upgrade_experience_card_schema(engine: AsyncEngine) -> dict[str, int]:
    async with engine.begin() as connection:
        return await connection.run_sync(_sync_upgrade)


def _sync_downgrade(connection) -> dict[str, int]:
    inspector = inspect(connection)
    dropped_columns = 0
    if CARD_TABLE in inspector.get_table_names():
        existing = {column["name"] for column in inspector.get_columns(CARD_TABLE)}
        # Drop in reverse order; SQLite >=3.35 and PostgreSQL support it.
        for name, _ddl_type in reversed(CARD_COLUMN_PLAN):
            if name in existing:
                connection.execute(
                    text(f"ALTER TABLE {CARD_TABLE} DROP COLUMN {name}")
                )
                dropped_columns += 1
    dropped_tables = 0
    for table in JOURNAL_TABLES:
        table_name = table.__tablename__
        if table_name in inspector.get_table_names():
            connection.execute(text(f"DROP TABLE {table_name}"))
            dropped_tables += 1
    return {"columns_dropped": dropped_columns, "tables_dropped": dropped_tables}


async def downgrade_experience_card_schema(engine: AsyncEngine) -> dict[str, int]:
    async with engine.begin() as connection:
        return await connection.run_sync(_sync_downgrade)


def card_schema_inventory() -> dict[str, object]:
    return {
        "schema_version": EXPERIENCE_CARD_SCHEMA_VERSION,
        "canonical_table": CARD_TABLE,
        "added_columns": [name for name, _ in CARD_COLUMN_PLAN],
        "journal_tables": [table.__tablename__ for table in JOURNAL_TABLES],
        "growth_table_count": len(GROWTH_TABLES),
        "generated_at": utcnow().isoformat(),
        "down_revision": "NOT_ASSIGNED (draft, integration-owned)",
    }


__all__ = [
    "CARD_COLUMN_PLAN",
    "EXPERIENCE_CARD_SCHEMA_VERSION",
    "card_schema_inventory",
    "downgrade_experience_card_schema",
    "upgrade_experience_card_schema",
]
