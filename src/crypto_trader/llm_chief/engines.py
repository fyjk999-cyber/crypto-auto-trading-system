"""Self-learning engines: review, pattern, coin, cluster, compression, retrieval, budget."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D
from crypto_trader.llm_chief.memory import MarketPattern, TradeEpisode


@dataclass
class ReviewReport:
    episode_id: str
    success_factors: list[str]
    failure_factors: list[str]
    mistakes: list[str]
    lessons: list[str]
    future_rules: list[str]
    confidence: Decimal


class TradeReviewEngine:
    def review(self, episode: TradeEpisode) -> ReviewReport:
        if episode.result == "WIN":
            return ReviewReport(
                episode_id=episode.episode_id,
                success_factors=["TREND_ALIGNMENT", "CONFIRMED_EVIDENCE"],
                failure_factors=[],
                mistakes=[],
                lessons=episode.lessons,
                future_rules=["REPEAT_SETUP"],
                confidence=D("0.8"),
            )
        return ReviewReport(
            episode_id=episode.episode_id,
            success_factors=[],
            failure_factors=["LATE_ENTRY", "WEAK_CONVICTION"],
            mistakes=episode.mistakes,
            lessons=episode.lessons,
            future_rules=["AVOID_SIMILAR_SETUP"],
            confidence=D("0.5"),
        )


class MarketPatternEngine:
    def build_pattern(
        self,
        *,
        pattern_id: str,
        regime: str,
        features: dict,
        strategy: str,
        sample_count: int,
        win_count: int,
        loss_count: int,
        profit_factor: Decimal,
    ) -> MarketPattern:
        total = win_count + loss_count
        win_rate = Decimal(win_count) / Decimal(total) if total else D("0")
        return MarketPattern(
            pattern_id=pattern_id,
            regime=regime,
            trend_state=features.get("trend", "UP"),
            volatility_state=features.get("volatility", "HIGH"),
            volume_state=features.get("volume", "HIGH"),
            strategy_family=strategy,
            sample_count=sample_count,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=win_rate,
            profit_factor=profit_factor,
            average_return=D("0.01"),
        )


class CoinBehaviorEngine:
    def update_profile(self, profile, episode: TradeEpisode) -> None:
        profile.update_from_episode(episode)
        if episode.result == "WIN":
            profile.behavior_tags.append("TREND_FRIENDLY")
        else:
            profile.behavior_tags.append("HIGH_RISK")
        profile.behavior_tags = list(dict.fromkeys(profile.behavior_tags))


class CoinClusterEngine:
    def cluster(self, profiles: list[dict], features: dict) -> str:
        beta = features.get("beta", 1.0)
        momentum = features.get("momentum", 0.0)
        if beta > 1.2 and momentum > 0:
            return "HIGH_BETA_MOMENTUM_ALT"
        if beta > 1.2:
            return "HIGH_BETA_ALT"
        if momentum > 0.5:
            return "MOMENTUM_ALT"
        return "LOW_VOL"


class ExperienceCompressionEngine:
    def compress(self, episodes: list[TradeEpisode], min_samples: int = 3) -> list[str]:
        if len(episodes) < min_samples:
            return []
        wins = [e for e in episodes if e.result == "WIN"]
        losses = [e for e in episodes if e.result == "LOSS"]
        rules = []
        if wins:
            rules.append(
                f"{len(wins)} winning trades shared: "
                f"{wins[0].lessons[0] if wins[0].lessons else 'confirm trend'}"
            )
        if losses:
            rules.append(
                f"{len(losses)} losing trades shared: "
                f"{losses[0].mistakes[0] if losses[0].mistakes else 'avoid late entry'}"
            )
        return rules


class MemoryRetrievalEngine:
    def retrieve(self, *, symbol: str, regime: str, memory, top_k: int = 5) -> list[dict]:
        episodes = memory.similar_episodes(symbol, regime, top_k=top_k)
        return [
            {
                "episode_id": e.episode_id,
                "symbol": e.symbol,
                "regime": e.market_regime,
                "result": e.result,
            }
            for e in episodes
        ]


class ContextBudgetManager:
    def __init__(self, normal_limit: int = 5000, deep_limit: int = 12000) -> None:
        self.normal_limit = normal_limit
        self.deep_limit = deep_limit

    def fit(self, context_estimate: int, *, deep_research: bool = False) -> bool:
        limit = self.deep_limit if deep_research else self.normal_limit
        return context_estimate <= limit
