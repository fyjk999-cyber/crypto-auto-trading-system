"""Persistent-style trading experience memory (versioned, replayable)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal


@dataclass
class TradeEpisode:
    episode_id: str
    symbol: str
    market_regime: str
    quant_evidence: list[dict]
    llm_thesis: str
    raw_llm_confidence: float
    conviction_score: float
    result: str
    gross_pnl: Decimal
    net_pnl: Decimal
    mistakes: list[str]
    lessons: list[str]
    version: int = 1
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class MarketPattern:
    pattern_id: str
    regime: str
    trend_state: str
    volatility_state: str
    volume_state: str
    strategy_family: str
    sample_count: int
    win_count: int
    loss_count: int
    win_rate: Decimal
    profit_factor: Decimal
    average_return: Decimal
    version: int = 1


class ExperienceMemory:
    def __init__(self) -> None:
        self.episodes: dict[str, TradeEpisode] = {}
        self.patterns: dict[str, MarketPattern] = {}
        self.lessons: list[dict] = []

    def store_episode(self, episode: TradeEpisode) -> None:
        self.episodes[episode.episode_id] = episode

    def update_pattern(self, pattern: MarketPattern) -> None:
        existing = self.patterns.get(pattern.pattern_id)
        pattern.version = (existing.version + 1) if existing else 1
        self.patterns[pattern.pattern_id] = pattern

    def similar_episodes(self, symbol: str, regime: str, top_k: int = 5) -> list[TradeEpisode]:
        # cross-coin: same symbol is only a ranking bonus, not a hard filter
        scored = []
        for episode in self.episodes.values():
            score = 0.0
            if episode.market_regime == regime:
                score += 2.0
            if episode.symbol == symbol:
                score += 1.0
            if score > 0:
                scored.append((score, episode))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [episode for _, episode in scored[:top_k]]

    def compress_experience(self, min_samples: int = 3) -> list[str]:
        if len(self.episodes) < min_samples:
            return []
        lessons = [e.lessons for e in self.episodes.values() if e.lessons]
        compressed = []
        for lesson in lessons[:3]:
            compressed.append(" | ".join(lesson))
        return compressed
