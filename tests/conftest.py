import pytest

from crypto_trader.persistence.database import Database


@pytest.fixture
async def database(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/crypto_test.db")
    await db.init_schema()
    yield db
    await db.close()


@pytest.fixture
async def session(database):
    async with database.session_factory() as s:
        yield s
