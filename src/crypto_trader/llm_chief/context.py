"""Chief trader decision context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ChiefTraderContext:
    symbol: str
    market_snapshot: dict
    regime: str
    quant_evidence: list[dict]
    portfolio_state: dict
    risk_summary: dict
    knowledge: list[dict] = field(default_factory=list)
    similar_episodes: list[dict] = field(default_factory=list)
    coin_profile: dict = field(default_factory=dict)
    compressed_experience: list[dict] = field(default_factory=list)
    failure_warnings: list[str] = field(default_factory=list)
    prepared_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def estimate_tokens(self) -> int:
        import json

        return (
            len(
                json.dumps(
                    {
                        "system": 600,
                        "market": self.market_snapshot,
                        "quant": self.quant_evidence,
                        "portfolio": self.portfolio_state,
                        "risk": self.risk_summary,
                        "knowledge": self.knowledge,
                        "episodes": self.similar_episodes,
                        "coin": self.coin_profile,
                        "experience": self.compressed_experience,
                    }
                )
            )
            // 4
            + 1000
        )
