import asyncio

from tests.conftest import make_paper_engine


class PositionManager:
    async def review(self, context, position):
        return None


class EvidenceRouter:
    async def run_forever(self):
        while True:
            await asyncio.sleep(3600)


async def test_entry_position_and_candle_work_have_independent_runtime_tasks(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.position_manager = PositionManager()
    engine.evidence_router = EvidenceRouter()
    await engine.start("run-independent-llm-scheduling")
    try:
        names = {task.get_name() for task in engine._tasks}
        assert {"engine-ticks", "llm-position-reviews", "closed-candle-evidence"} <= names
    finally:
        await engine.stop()


async def test_slow_entry_llm_does_not_block_position_review(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    started = asyncio.Event()
    reviewed = asyncio.Event()

    class SlowStrategy:
        name = "slow-entry"

        async def on_market_data(self, context):
            started.set()
            await asyncio.sleep(0.3)
            return []

    class PositionManager:
        async def review(self, context, position):
            reviewed.set()
            return None

    async def positions():
        return {
            "BTCUSDT": type(
                "P",
                (),
                {"symbol": "BTCUSDT", "quantity": 1},
            )()
        }

    async def strategy_context(symbol=None):
        return object()

    engine.strategies = [SlowStrategy()]
    engine.position_manager = PositionManager()
    engine.portfolio.get_positions = positions
    engine._strategy_context = strategy_context

    entry_task = asyncio.create_task(engine.tick(include_position_reviews=False))
    await asyncio.wait_for(started.wait(), timeout=1)
    review_task = asyncio.create_task(engine._review_positions_once())
    await asyncio.wait_for(reviewed.wait(), timeout=0.2)
    await asyncio.wait_for(review_task, timeout=0.2)
    assert not entry_task.done()
    await asyncio.wait_for(entry_task, timeout=1)


async def test_slow_position_review_cannot_delay_other_due_positions(database):
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.position_review_timeout_seconds = 0.1
    engine.position_review_interval_seconds = 0.05
    reviewed = []

    class SlowStrategy:
        name = "slow-entry"

        async def on_market_data(self, context):
            await asyncio.sleep(0.5)
            return []

    class PositionManager:
        async def review(self, context, position):
            if position.symbol == "SLOWUSDT":
                await asyncio.sleep(5)
            reviewed.append(position.symbol)
            return None

    async def positions():
        return {
            symbol: type(
                "P",
                (),
                {
                    "symbol": symbol,
                    "quantity": 1,
                    "avg_entry_price": None,
                    "contract_size": 1,
                    "contract_multiplier": 1,
                },
            )()
            for symbol in ("SLOWUSDT", "FAST1USDT", "FAST2USDT")
        }

    async def strategy_context(symbol=None):
        return object()

    engine.strategies = [SlowStrategy()]
    engine.position_manager = PositionManager()
    engine.portfolio.get_positions = positions
    engine._strategy_context = strategy_context

    entry_task = asyncio.create_task(engine.tick(include_position_reviews=False))
    await asyncio.wait_for(engine._review_positions_once(), timeout=0.3)
    assert set(reviewed) == {"FAST1USDT", "FAST2USDT"}
    assert not entry_task.done()
    await asyncio.wait_for(entry_task, timeout=1)
