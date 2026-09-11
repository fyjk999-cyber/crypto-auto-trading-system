"""G09 schema/migration/lineage tests (TEST_ONLY)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from crypto_trader.learning.growth_experience import AdaptiveCardStore
from crypto_trader.learning.growth_v2_contracts import (
    OP_KEEP,
    OP_UPDATE,
    CardUpdateProposal,
)
from crypto_trader.learning.growth_v2_migration import (
    CARD_COLUMN_PLAN,
    downgrade_experience_card_schema,
    upgrade_experience_card_schema,
)
from tests.growth_system_v2.conftest import (
    AS_OF,
    market_context,
    seed_card,
    trigger,
)


async def _columns(engine, table: str) -> set[str]:
    async with engine.connect() as connection:
        def _read(sync_connection):
            return {column["name"] for column in inspect(sync_connection).get_columns(table)}

        return await connection.run_sync(_read)


async def test_fresh_schema_has_all_card_columns(v2_db):
    columns = await _columns(v2_db.engine, "ai_compressed_experience")
    for name, _ddl in CARD_COLUMN_PLAN:
        assert name in columns


async def test_legacy_upgrade_preserves_data_and_is_repeatable(tmp_path):
    path = tmp_path / "legacy_cards.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                create table ai_compressed_experience (
                    id integer primary key autoincrement,
                    rule_id varchar(64) unique,
                    symbol varchar(32),
                    title varchar(200),
                    content varchar(2000),
                    source_episode_count integer default 0,
                    version integer default 1,
                    applicability_scope_json json,
                    created_at datetime
                )
                """
            )
        )
        await connection.execute(
            text(
                "insert into ai_compressed_experience "
                "(rule_id, symbol, title, content, source_episode_count, version, created_at) "
                "values ('legacy_rule','BTCUSDT','Legacy title','Legacy content',2,1,"
                "'2026-08-01 00:00:00')"
            )
        )
    try:
        first = await upgrade_experience_card_schema(engine)
        assert first["columns_added"] == len(CARD_COLUMN_PLAN)
        columns = await _columns(engine, "ai_compressed_experience")
        assert "trigger_signature_json" in columns and "status" in columns
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "select rule_id,title,content,experience_type,status,known_at "
                        "from ai_compressed_experience where rule_id='legacy_rule'"
                    )
                )
            ).first()
        assert row is not None
        assert row[1] == "Legacy title" and row[2] == "Legacy content"
        assert row[3] == "COMPRESSED_EXPERIENCE"
        assert row[4] == "WATCH"
        assert row[5] is not None
        # Repeat upgrade is a no-op and does not overwrite the legacy row.
        second = await upgrade_experience_card_schema(engine)
        assert second["columns_added"] == 0
        # Downgrade / re-upgrade keeps the project migration reversible.
        downgraded = await downgrade_experience_card_schema(engine)
        assert downgraded["columns_dropped"] == len(CARD_COLUMN_PLAN)
        reupgraded = await upgrade_experience_card_schema(engine)
        assert reupgraded["columns_added"] == len(CARD_COLUMN_PLAN)
        columns_after = await _columns(engine, "ai_compressed_experience")
        assert "status" in columns_after
    finally:
        await engine.dispose()


async def test_card_roundtrip_and_version_lineage(v2_db):
    store = AdaptiveCardStore(v2_db.session_factory)
    await seed_card(v2_db, rule_id="card_lineage", status="CANDIDATE")
    card = await store.get_card("card_lineage")
    assert card is not None
    assert card.trigger is not None and card.trigger.signature_hash()
    assert card.context is not None and card.context.regime == "BULL"

    update = CardUpdateProposal(
        operation=OP_UPDATE,
        rationale="NEW_SUPPORT",
        card_rule_id="card_lineage",
        source_episode_ids=["ep_4"],
        supporting_episode_ids=["ep_4"],
        evidence_refs=["episode:ep_4"],
        proposed_status="ACTIVE",
    ).finalize()
    first = await store.apply(update)
    assert first.version == 2 and first.status == "ACTIVE"

    keep = CardUpdateProposal(
        operation=OP_KEEP,
        rationale="NO_NEW_INFORMATION",
        card_rule_id="card_lineage",
    ).finalize()
    kept = await store.apply(keep)
    assert kept.version == 2  # KEEP never creates a pointless version
    updated = await store.get_card("card_lineage")
    assert updated is not None and updated.version == 2

    history = await store.history("card_lineage")
    versions = [(row.version, row.operation) for row in history]
    assert versions == [(1, "CREATE"), (2, "UPDATE"), (2, "KEEP")]
    assert history[0].snapshot_json["version"] == 1
    assert history[1].snapshot_json["version"] == 2

    # The original v1 snapshot is still queryable after v2 overwrote current.
    v1 = [row for row in history if row.version == 1][0]
    assert v1.snapshot_json["status"] == "CANDIDATE"
    assert v1.snapshot_json["sample_count"] == 3


async def test_future_version_is_visible_at_historical_as_of(v2_db):
    """In-place current row must not leak a post-as_of revision into history."""
    from crypto_trader.learning.growth_card_retrieval import ExperienceCardRetriever

    await seed_card(
        v2_db,
        rule_id="card_hist",
        status="ACTIVE",
        updated_at=AS_OF - timedelta(days=1),
    )
    store = AdaptiveCardStore(v2_db.session_factory)
    future = CardUpdateProposal(
        operation=OP_UPDATE,
        rationale="FUTURE_REVISION",
        card_rule_id="card_hist",
        proposed_guidance={"summary": "future wording"},
    ).finalize()
    await store.apply(future)
    retriever = ExperienceCardRetriever(v2_db.session_factory)
    historical = await retriever.retrieve(
        trigger=trigger(),
        context=market_context(),
        as_of=AS_OF,
        top_k=3,
    )
    # Current v2 exists after AS_OF; the visible card must be the v1 journal
    # snapshot, and its guidance must not contain the future wording.
    assert historical.selected, historical.excluded_reasons
    selected = historical.selected[0].card
    assert selected is not None
    assert selected.version == 1
    assert selected.guidance.get("summary") != "future wording"
