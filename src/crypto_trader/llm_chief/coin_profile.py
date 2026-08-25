"""Coin behavioral profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class CoinProfile:
    symbol: str
    sample_count: int = 0
    regime_distribution: dict = field(default_factory=dict)
    strategy_performance: dict = field(default_factory=dict)
    best_setups: list[str] = field(default_factory=list)
    worst_setups: list[str] = field(default_factory=list)
    winning_drivers: list[str] = field(default_factory=list)
    failure_drivers: list[str] = field(default_factory=list)
    btc_dependency: float = 0.0
    behavior_tags: list[str] = field(default_factory=list)
    profile_summary: str = ""
    version: int = 1
    first_sample_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_sample_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def update_from_episode(self, episode) -> None:
        self.sample_count += 1
        self.last_sample_at = datetime.now(UTC).isoformat()
        self.regime_distribution[episode.market_regime] = (
            self.regime_distribution.get(episode.market_regime, 0) + 1
        )
        if episode.result == "WIN":
            self.winning_drivers.extend(episode.lessons)
        else:
            self.failure_drivers.extend(episode.mistakes)
        if self.sample_count < 10:
            self.profile_summary = "EXPERIMENTAL"
        elif self.sample_count < 30:
            self.profile_summary = "LOW"
        elif self.sample_count < 100:
            self.profile_summary = "MEDIUM"
        else:
            self.profile_summary = "HIGH"
        self.version += 1


class CoinProfileStore:
    def __init__(self) -> None:
        self.profiles: dict[str, CoinProfile] = {}

    def get_or_create(self, symbol: str) -> CoinProfile:
        if symbol not in self.profiles:
            self.profiles[symbol] = CoinProfile(symbol=symbol)
        return self.profiles[symbol]
