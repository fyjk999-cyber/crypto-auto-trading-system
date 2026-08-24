from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class IntervalScheduler:
    def __init__(self, interval_seconds: float, callback: Callable[[], Awaitable[None]]) -> None:
        self.interval_seconds = interval_seconds
        self.callback = callback
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            await self.callback()

    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self._run())
        return self._task

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
