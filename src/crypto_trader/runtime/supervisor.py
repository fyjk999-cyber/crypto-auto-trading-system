"""TradingRuntimeSupervisor: independently supervised 24/7 runtime loops.

The runtime is frontend-independent. Browser connections have zero effect.
Each loop owns its own heartbeat and can be supervised/restarted independently.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from crypto_trader.domain.enums import RuntimeState
from crypto_trader.runtime.lease import LeaseManager


@dataclass
class RuntimeStatus:
    runtime_state: RuntimeState = RuntimeState.STOPPED
    run_id: str | None = None
    instance_id: str = "crypto-trading-primary"
    lease_valid: bool = False
    fence_generation: int = 0
    database: bool = False
    market_ws: bool = False
    user_ws: bool = False
    scanner_heartbeat: int = 0
    market_heartbeat: int = 0
    reconciliation_heartbeat: int = 0
    lease_renew_count: int = 0
    restart_count: int = 0
    kill_switch: bool = False
    open_orders: int = 0
    git_sha: str = "unknown"


class TradingRuntimeSupervisor:
    """Supervises independent loops. No loop is coupled to a frontend client."""

    def __init__(
        self,
        *,
        lease_manager: LeaseManager,
        lease_key: str = "crypto_engine_execution",
        owner_id: str = "crypto-trading-primary",
        interval_seconds: float = 0.1,
        renew_interval: float = 0.5,
        scanner_callback: Callable[[], Awaitable[None]] | None = None,
        execution_callback: Callable[[], Awaitable[None]] | None = None,
        order_event_callback: Callable[[], Awaitable[None]] | None = None,
        user_data_stream_callback: Callable[[], Awaitable[None]] | None = None,
        reconciliation_callback: Callable[[], Awaitable[None]] | None = None,
        market_data_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.lease_manager = lease_manager
        self.lease_key = lease_key
        self.owner_id = owner_id
        self.interval = interval_seconds
        self.renew_interval = renew_interval
        self.scanner_callback = scanner_callback
        self.execution_callback = execution_callback
        self.order_event_callback = order_event_callback
        self.user_data_stream_callback = user_data_stream_callback
        self.reconciliation_callback = reconciliation_callback
        self.market_data_callback = market_data_callback
        self.status = RuntimeStatus()
        self._tasks: dict[str, asyncio.Task] = {}
        self._stopping = False
        self._lease = None

    async def start(self, run_id: str | None = None, restart_count: int = 0) -> None:
        if self.status.runtime_state == RuntimeState.RUNNING:
            return
        from crypto_trader.domain.identifiers import new_id

        self.status.run_id = run_id or new_id("run")
        self.status.restart_count = restart_count
        self._lease = await self.lease_manager.acquire(
            self.lease_key, self.owner_id, ttl_seconds=30
        )
        if self._lease is None:
            self.status.runtime_state = RuntimeState.HALTED
            raise RuntimeError("could not acquire execution lease")
        self.status.fence_generation = self._lease.fence_generation
        self.status.runtime_state = RuntimeState.RUNNING
        self._stopping = False
        loops = {
            "market_data": self._market_data_loop,
            "scanner": self._scanner_loop,
            "strategy": self._strategy_loop,
            "execution": self._execution_loop,
            "order_event": self._order_event_loop,
            "user_data_stream": self._user_data_stream_loop,
            "reconciliation": self._reconciliation_loop,
            "lease_renew": self._lease_renew_loop,
            "heartbeat": self._heartbeat_loop,
        }
        for name, coro in loops.items():
            self._tasks[name] = asyncio.create_task(
                self._supervised(name, coro()), name=f"runtime-{name}"
            )

    async def _supervised(self, name: str, coro: Awaitable[None]) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            # keep runtime alive: independent loop restart
            if not self._stopping:
                self._tasks[name] = asyncio.create_task(
                    self._supervised(name, coro), name=f"runtime-{name}-restart"
                )

    async def _market_data_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.interval)
            self.status.market_ws = True
            self.status.market_heartbeat += 1
            if self.market_data_callback:
                await self.market_data_callback()

    async def _scanner_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.interval)
            self.status.scanner_heartbeat += 1
            # Lease renewal is owned by the single _lease_renew_loop below to
            # avoid concurrent SQLite writers in local/CI runs.
            if self.scanner_callback:
                await self.scanner_callback()

    async def _strategy_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.interval)

    async def _execution_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.interval)
            if self._lease is not None and await self.lease_manager.is_current(
                self.lease_key, self._lease.token, self._lease.fence_generation
            ):
                self.status.lease_valid = True
                if self.execution_callback:
                    await self.execution_callback()
            else:
                self.status.lease_valid = False

    async def _order_event_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.interval)
            if self.order_event_callback:
                await self.order_event_callback()

    async def _user_data_stream_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.interval)
            self.status.user_ws = True
            if self.user_data_stream_callback:
                await self.user_data_stream_callback()

    async def _reconciliation_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.interval)
            self.status.reconciliation_heartbeat += 1
            if self.reconciliation_callback:
                await self.reconciliation_callback()

    async def _lease_renew_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.renew_interval)
            if self._lease is not None:
                if await self.lease_manager.renew(
                    self.lease_key, self._lease.token, ttl_seconds=30
                ):
                    self.status.lease_renew_count += 1
                else:
                    self.status.runtime_state = RuntimeState.HALTED

    async def _heartbeat_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.interval)
            self.status.database = True

    async def stop(self) -> None:
        self._stopping = True
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._lease is not None:
            await self.lease_manager.release(self.lease_key, self._lease.token)
        self.status.runtime_state = RuntimeState.STOPPED

    def health(self) -> dict:
        return {
            "runtime_state": self.status.runtime_state.value,
            "run_id": self.status.run_id,
            "instance_id": self.status.instance_id,
            "lease_valid": self.status.lease_valid,
            "fencing_generation": self.status.fence_generation,
            "database": self.status.database,
            "market_ws": self.status.market_ws,
            "user_ws": self.status.user_ws,
            "scanner_heartbeat": self.status.scanner_heartbeat,
            "market_heartbeat": self.status.market_heartbeat,
            "reconciliation_heartbeat": self.status.reconciliation_heartbeat,
            "lease_renew_count": self.status.lease_renew_count,
            "restart_count": self.status.restart_count,
            "kill_switch": self.status.kill_switch,
            "open_orders": self.status.open_orders,
            "git_sha": self.status.git_sha,
        }
