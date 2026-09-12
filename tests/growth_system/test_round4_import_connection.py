"""Round-4 T12/T13: async_creator alternate DB must fail the importer guard."""

from __future__ import annotations

import aiosqlite
import pytest
from sqlalchemy import select

from crypto_trader.learning.growth_import import ImportSafetyError, LegacyImporter
from crypto_trader.learning.growth_models import (
    GrowthImportBatchORM,
    GrowthLegacyObservationORM,
    create_growth_schema,
)
from crypto_trader.persistence.database import Database
from tests.growth_system.conftest import assert_test_database_path
from tests.growth_system.test_round2_import_safety import _make_source


async def _database(path) -> Database:
    assert_test_database_path(str(path))
    database = Database(f"sqlite+aiosqlite:///{path}")
    await database.init_schema()
    await create_growth_schema(database.engine)
    return database


async def _alternate_database(label, actual) -> Database:
    assert_test_database_path(str(label))

    async def factory():
        return await aiosqlite.connect(actual)

    database = Database(
        f"sqlite+aiosqlite:///{label}",
        async_creator=factory,
    )
    await database.init_schema()
    await create_growth_schema(database.engine)
    return database


async def _count(database, model) -> int:
    async with database.session_factory() as session:
        return len((await session.execute(select(model))).scalars().all())


async def test_t12_async_creator_alternate_db_cannot_bypass_import(
    tmp_path, monkeypatch
):
    approved_path = tmp_path / "approved.db"
    actual_path = tmp_path / "alternate.db"
    approved = await _database(approved_path)
    malicious = await _alternate_database(approved_path, actual_path)
    source = tmp_path / "source.db"
    _make_source(source)
    importer = LegacyImporter(
        malicious.session_factory,
        target_path=str(approved_path),
        test_only=True,
    )
    plan = importer.build_plan(str(source))
    with pytest.raises(ImportSafetyError):
        await importer.import_plan(plan)
    assert await _count(approved, GrowthLegacyObservationORM) == 0
    assert await _count(malicious, GrowthLegacyObservationORM) == 0
    await approved.close()
    await malicious.close()


async def test_t13_async_creator_cannot_bypass_rollback(tmp_path):
    approved_path = tmp_path / "approved.db"
    actual_path = tmp_path / "alternate.db"
    approved = await _database(approved_path)
    source = tmp_path / "source.db"
    _make_source(source)
    legitimate = LegacyImporter(
        approved.session_factory,
        target_path=str(approved_path),
        test_only=True,
    )
    plan = legitimate.build_plan(str(source))
    report = await legitimate.import_plan(plan)
    assert await _count(approved, GrowthLegacyObservationORM) > 0

    malicious = await _alternate_database(approved_path, actual_path)
    importer = LegacyImporter(
        malicious.session_factory,
        target_path=str(approved_path),
        test_only=True,
    )
    with pytest.raises(ImportSafetyError):
        await importer.rollback(report.batch_id)
    assert await _count(approved, GrowthLegacyObservationORM) > 0
    assert await _count(malicious, GrowthLegacyObservationORM) == 0
    async with approved.session_factory() as session:
        batch = await session.get(GrowthImportBatchORM, report.batch_id)
        assert batch.status == "COMPLETED"
    await approved.close()
    await malicious.close()
