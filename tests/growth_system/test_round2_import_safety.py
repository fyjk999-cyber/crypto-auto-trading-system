"""Round-2 import-target / rollback / resume identity tests (R09-R11)."""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select

from crypto_trader.learning.growth_import import (
    ImportSafetyError,
    InjectedImportFailure,
    LegacyImporter,
)
from crypto_trader.learning.growth_models import (
    GrowthImportBatchORM,
    GrowthLegacyObservationORM,
    create_growth_schema,
)
from crypto_trader.persistence.database import Database
from tests.growth_system.conftest import assert_test_database_path


def _make_source(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
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
            ('ep_1','BTCUSDT','TREND','100','102','2','WIN','2026-09-09 10:00:00');
        insert into trade_memory_records values
            ('dec_1','BTCUSDT','LONG','TREND','1.5','0.1','0','2026-09-09 11:00:00');
        insert into learning_lessons values (1, 'Always buy the breakout');
        """
    )
    connection.commit()
    connection.close()


async def _target(tmp_path: Path, name: str) -> Database:
    path = tmp_path / name
    assert_test_database_path(str(path))
    database = Database(f"sqlite+aiosqlite:///{path}")
    await database.init_schema()
    await create_growth_schema(database.engine)
    return database


async def _observation_count(database: Database) -> int:
    async with database.session_factory() as session:
        return len(
            (
                await session.execute(select(GrowthLegacyObservationORM))
            ).scalars().all()
        )


async def test_t13_target_path_must_match_real_connection(tmp_path):
    target_a = await _target(tmp_path, "a.db")
    target_b = await _target(tmp_path, "b.db")
    source = tmp_path / "legacy.db"
    _make_source(source)
    importer = LegacyImporter(
        target_a.session_factory,
        target_path=str(tmp_path / "b.db"),
        test_only=True,
    )
    plan = importer.build_plan(str(source))
    with pytest.raises(ImportSafetyError):
        await importer.import_plan(plan)
    assert await _observation_count(target_a) == 0
    assert await _observation_count(target_b) == 0
    await target_a.close()
    await target_b.close()


async def test_t14_unauthorized_rollback_deletes_nothing(tmp_path):
    target = await _target(tmp_path, "target.db")
    source = tmp_path / "legacy.db"
    _make_source(source)
    authorized = LegacyImporter(
        target.session_factory,
        target_path=str(tmp_path / "target.db"),
        test_only=True,
    )
    plan = authorized.build_plan(str(source))
    report = await authorized.import_plan(plan)
    assert await _observation_count(target) > 0

    unauthorized = LegacyImporter(
        target.session_factory,
        target_path=str(tmp_path / "target.db"),
        test_only=False,
    )
    with pytest.raises(ImportSafetyError):
        await unauthorized.rollback(report.batch_id)
    assert await _observation_count(target) > 0
    async with target.session_factory() as session:
        batch = await session.get(GrowthImportBatchORM, report.batch_id)
        assert batch.status != "ROLLED_BACK"
    await target.close()


async def test_t15_rollback_wrong_batch_identity_deletes_nothing(tmp_path):
    target = await _target(tmp_path, "target.db")
    source = tmp_path / "legacy.db"
    _make_source(source)
    importer = LegacyImporter(
        target.session_factory,
        target_path=str(tmp_path / "target.db"),
        test_only=True,
    )
    plan = importer.build_plan(str(source))
    report = await importer.import_plan(plan)
    before = await _observation_count(target)
    with pytest.raises(ImportSafetyError):
        await importer.rollback(
            report.batch_id, expected_source_sha256="0" * 64
        )
    with pytest.raises(ImportSafetyError):
        await importer.rollback(report.batch_id, expected_plan_hash="0" * 64)
    assert await _observation_count(target) == before
    await target.close()


async def test_t16_t17_resume_identity_mismatch_rejected(tmp_path):
    target = await _target(tmp_path, "target.db")
    source = tmp_path / "legacy.db"
    _make_source(source)
    importer = LegacyImporter(
        target.session_factory,
        target_path=str(tmp_path / "target.db"),
        test_only=True,
    )
    plan = importer.build_plan(str(source))
    with pytest.raises(InjectedImportFailure):
        await importer.import_plan(plan, fail_after=1, batch_id="batch_resume")
    before = await _observation_count(target)

    wrong_source = dataclasses.replace(plan, source_sha256="1" * 64)
    with pytest.raises(ImportSafetyError):
        await importer.import_plan(wrong_source, resume_batch_id="batch_resume")
    assert await _observation_count(target) == before

    wrong_plan = dataclasses.replace(plan, plan_hash="2" * 64)
    with pytest.raises(ImportSafetyError):
        await importer.import_plan(wrong_plan, resume_batch_id="batch_resume")
    assert await _observation_count(target) == before
    await target.close()
