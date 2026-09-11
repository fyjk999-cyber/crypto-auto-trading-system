"""G05: legacy inventory, isolated import, resume and rollback (TEST_ONLY)."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select

from crypto_trader.learning.growth_import import (
    BATCH_FAILED,
    BATCH_ROLLED_BACK,
    CONTENT_CONFLICT,
    DUPLICATE_SUSPECT,
    LEGACY_OBSERVATION,
    QUARANTINED,
    ImportSafetyError,
    InjectedImportFailure,
    LegacyImporter,
)
from crypto_trader.learning.growth_models import (
    GrowthImportBatchORM,
    GrowthImportItemORM,
    GrowthLegacyObservationORM,
    create_growth_schema,
)
from crypto_trader.persistence.database import Database
from tests.growth_system.conftest import assert_test_database_path


def _make_source(path: Path, *, episode_pnl: str = "2", decision_pnl: str = "1.5") -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        f"""
        create table ai_trade_episodes (
            episode_id text primary key,
            symbol text,
            market_regime text,
            entry_price text,
            exit_price text,
            pnl text,
            result text,
            created_at text
        );
        create table trade_memory_records (
            decision_id text primary key,
            symbol text,
            side text,
            regime text,
            realized_pnl text,
            fees text,
            funding_pnl text,
            timestamp text
        );
        create table learning_lessons (id integer primary key, title text);
        insert into ai_trade_episodes values
            ('ep_1','BTCUSDT','TREND','100','102','{episode_pnl}','WIN','2026-09-09 10:00:00');
        insert into trade_memory_records values
            ('dec_1','BTCUSDT','LONG','TREND','{decision_pnl}','0.1','0','2026-09-09 11:00:00'),
            ('dec_2','ETHUSDT','SHORT','RANGE','-0.5','0.2','0','2026-09-09 12:00:00');
        insert into learning_lessons values (1, 'Always buy the breakout');
        """
    )
    connection.commit()
    connection.close()


@pytest.fixture
async def import_target(tmp_path):
    path = tmp_path / "import_target.db"
    assert_test_database_path(str(path))
    database = Database(f"sqlite+aiosqlite:///{path}")
    await database.init_schema()
    await create_growth_schema(database.engine)
    yield database
    await database.close()


def _target_path(database) -> str:
    return database.url.replace("sqlite+aiosqlite:///", "")


async def _observations(database) -> list[GrowthLegacyObservationORM]:
    async with database.session_factory() as session:
        return (
            await session.execute(
                select(GrowthLegacyObservationORM).order_by(
                    GrowthLegacyObservationORM.batch_id,
                    GrowthLegacyObservationORM.observation_id,
                )
            )
        ).scalars().all()


async def _items(database) -> list[GrowthImportItemORM]:
    async with database.session_factory() as session:
        return (
            await session.execute(
                select(GrowthImportItemORM).order_by(GrowthImportItemORM.id)
            )
        ).scalars().all()


def test_import_target_guard_refuses_production_path(import_target):
    with pytest.raises(ImportSafetyError):
        LegacyImporter(
            import_target.session_factory,
            target_path="/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-fullmarket/data/crypto_trader.db",
            test_only=True,
        )
    unauthorized = LegacyImporter(import_target.session_factory, target_path="/tmp/ok.db")
    with pytest.raises(ImportSafetyError):
        unauthorized.require_import_authorization()


async def test_inventory_and_plan_are_read_only(tmp_path, import_target):
    source = tmp_path / "legacy.db"
    _make_source(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    importer = LegacyImporter(import_target.session_factory, test_only=True)
    inventory = importer.inventory(str(source))
    plan = importer.build_plan(str(source))
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert before == after
    assert {entry["table"] for entry in inventory} >= {
        "ai_trade_episodes",
        "trade_memory_records",
        "learning_lessons",
    }
    assert len(plan.items) == 4
    assert plan.dispositions[LEGACY_OBSERVATION] == 3
    assert plan.dispositions[QUARANTINED] == 1
    assert all(len(item.namespace) == 64 for item in plan.items)
    lesson = [item for item in plan.items if item.source_table == "learning_lessons"][0]
    assert lesson.disposition == QUARANTINED
    assert lesson.reason == "LEGACY_LESSON_WITHOUT_EVIDENCE_REFS"


async def test_import_creates_legacy_observations_not_canonical_facts(
    tmp_path, import_target
):
    source = tmp_path / "legacy.db"
    _make_source(source)
    importer = LegacyImporter(
        import_target.session_factory,
        target_path=_target_path(import_target),
        test_only=True,
    )
    plan = importer.build_plan(str(source))
    report = await importer.import_plan(plan)
    assert report.status == "COMPLETED"
    assert report.imported == 3
    assert report.quarantined == 1
    observations = await _observations(import_target)
    assert len(observations) == 4
    episode = [row for row in observations if row.proof_kind == "LEGACY_AI_EPISODE"][0]
    assert episode.status == LEGACY_OBSERVATION
    assert episode.content_hash
    assert episode.economic_closed_at is not None
    assert episode.imported_at is not None
    assert episode.known_at >= episode.imported_at
    # The legacy PnL is data inside the observation, never a pattern/factual row.
    assert episode.source_json_sanitized["pnl"] == "2"
    async with import_target.session_factory() as session:
        from crypto_trader.persistence.models import TradeEpisodeORM

        assert (
            await session.execute(select(TradeEpisodeORM))
        ).scalars().all() == []


async def test_reimport_is_idempotent(tmp_path, import_target):
    source = tmp_path / "legacy.db"
    _make_source(source)
    importer = LegacyImporter(
        import_target.session_factory,
        target_path=_target_path(import_target),
        test_only=True,
    )
    plan = importer.build_plan(str(source))
    first = await importer.import_plan(plan)
    second = await importer.import_plan(plan)
    assert first.status == "COMPLETED"
    assert second.idempotent is True
    assert second.batch_id == first.batch_id
    assert len(await _observations(import_target)) == 4
    assert len(await _items(import_target)) == 4


async def test_same_source_id_different_content_conflict(tmp_path, import_target):
    source = tmp_path / "legacy.db"
    _make_source(source, episode_pnl="2")
    importer = LegacyImporter(
        import_target.session_factory,
        target_path=_target_path(import_target),
        test_only=True,
    )
    first_plan = importer.build_plan(str(source))
    await importer.import_plan(first_plan)

    changed_source = tmp_path / "legacy_changed.db"
    _make_source(changed_source, episode_pnl="999")
    changed_plan = importer.build_plan(
        str(changed_source), source_sha_override=first_plan.source_sha256
    )
    assert changed_plan.plan_hash != first_plan.plan_hash
    conflict_report = await importer.import_plan(changed_plan, batch_id="batch_conflict")
    assert conflict_report.conflicts >= 1
    conflicts = [
        item
        for item in await _items(import_target)
        if item.disposition == CONTENT_CONFLICT
    ]
    assert conflicts and conflicts[0].reason == "SAME_NAMESPACE_DIFFERENT_CONTENT"
    # The original observation is not overwritten.
    observations = await _observations(import_target)
    episode = [row for row in observations if row.proof_kind == "LEGACY_AI_EPISODE"][0]
    assert episode.source_json_sanitized["pnl"] == "2"


async def test_near_duplicate_is_suspect_but_never_merged(tmp_path, import_target):
    source_a = tmp_path / "legacy_a.db"
    source_b = tmp_path / "legacy_b.db"
    _make_source(source_a)
    shutil.copy(source_a, source_b)
    # Same economic rows, different database bytes/identity.
    tweak = sqlite3.connect(source_b)
    tweak.execute("pragma user_version=99")
    tweak.commit()
    tweak.close()
    importer = LegacyImporter(
        import_target.session_factory,
        target_path=_target_path(import_target),
        test_only=True,
    )
    await importer.import_plan(importer.build_plan(str(source_a)))
    report = await importer.import_plan(importer.build_plan(str(source_b)))
    assert report.quarantined >= 1
    suspect_items = [
        item for item in await _items(import_target) if item.disposition == DUPLICATE_SUSPECT
    ]
    assert suspect_items
    assert suspect_items[0].reason == "NEAR_DUPLICATE_SYMBOL_TIME_PNL_NOT_MERGED"
    observations = await _observations(import_target)
    # Both source observations still exist; similarity never merged them.
    assert len(observations) == 8
    assert len({row.observation_id for row in observations}) == 8


async def test_different_account_gets_distinct_observation(tmp_path, import_target):
    source = tmp_path / "legacy.db"
    _make_source(source)
    importer = LegacyImporter(
        import_target.session_factory,
        target_path=_target_path(import_target),
        test_only=True,
    )
    account_one = importer.build_plan(str(source), account_id="acct-1")
    account_two = importer.build_plan(
        str(source),
        account_id="acct-2",
        source_sha_override=account_one.source_sha256,
    )
    await importer.import_plan(account_one)
    await importer.import_plan(account_two, batch_id="batch_acct_2")
    observations = await _observations(import_target)
    accounts = {row.account_id for row in observations}
    assert accounts == {"acct-1", "acct-2"}
    assert len(observations) == 8


async def test_failure_then_resume_does_not_duplicate(tmp_path, import_target):
    source = tmp_path / "legacy.db"
    _make_source(source)
    importer = LegacyImporter(
        import_target.session_factory,
        target_path=_target_path(import_target),
        test_only=True,
    )
    plan = importer.build_plan(str(source))
    with pytest.raises(InjectedImportFailure):
        await importer.import_plan(plan, fail_after=2, batch_id="batch_resume")
    async with import_target.session_factory() as session:
        batch = await session.get(GrowthImportBatchORM, "batch_resume")
        assert batch.status == BATCH_FAILED
    resumed = await importer.import_plan(plan, resume_batch_id="batch_resume")
    assert resumed.resumed is True
    assert resumed.status == "COMPLETED"
    observations = await _observations(import_target)
    assert len(observations) == 4
    assert len({row.observation_id for row in observations}) == 4
    assert len(await _items(import_target)) == 4


async def test_rollback_is_batch_scoped_and_leaves_source_untouched(tmp_path, import_target):
    source = tmp_path / "legacy.db"
    _make_source(source)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    importer = LegacyImporter(
        import_target.session_factory,
        target_path=_target_path(import_target),
        test_only=True,
    )
    first = importer.build_plan(str(source), account_id="acct-1")
    second = importer.build_plan(
        str(source), account_id="acct-2", source_sha_override=first.source_sha256
    )
    await importer.import_plan(first)
    report_two = await importer.import_plan(second, batch_id="batch_two")
    result = await importer.rollback(report_two.batch_id)
    assert result["observations_deleted"] == 4
    remaining = await _observations(import_target)
    assert remaining and all(row.batch_id != "batch_two" for row in remaining)
    async with import_target.session_factory() as session:
        rolled = await session.get(GrowthImportBatchORM, "batch_two")
        assert rolled.status == BATCH_ROLLED_BACK
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
