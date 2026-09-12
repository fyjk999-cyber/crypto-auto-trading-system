"""Long-term market history encyclopedia."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketEvent:
    year: int
    event_type: str
    description: str


class MarketEncyclopedia:
    def __init__(self) -> None:
        self.events: list[MarketEvent] = []

    def add_event(self, year: int, event_type: str, description: str) -> None:
        self.events.append(MarketEvent(year, event_type, description))

    def similar_periods(self, *, event_type: str) -> list[MarketEvent]:
        return [e for e in self.events if e.event_type == event_type]
