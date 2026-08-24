"""Minimal async event bus for in-process runtime events."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[object], Awaitable[None]]]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Callable[[object], Awaitable[None]]) -> None:
        self._subscribers[event_type].append(handler)

    async def publish(self, event_type: str, event: object) -> None:
        for handler in list(self._subscribers.get(event_type, [])):
            await handler(event)
        for handler in list(self._subscribers.get("*", [])):
            await handler(event)

    def subscriber_count(self, event_type: str) -> int:
        return len(self._subscribers.get(event_type, []))
