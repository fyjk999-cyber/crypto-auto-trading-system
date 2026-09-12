"""Coin selection and AI opportunity ranking."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_trader.domain.money import D


@dataclass
class CoinScore:
    symbol: str
    direction: str
    score: int
    reasoning: str


class DeepSeekMarketSelector:
    def rank(self, candidates: list[dict]) -> list[CoinScore]:
        scored = []
        for c in candidates:
            score = D("50")
            if c.get("trend") == "BULL":
                score += D("15")
            elif c.get("trend") == "BEAR":
                score -= D("15")
            score += D(str(c.get("momentum", "0"))) * D("10")
            score += D(str(c.get("liquidity", "0"))) * D("5")
            score -= D(str(c.get("volatility", "0"))) * D("2")
            score += D(str(c.get("funding_score", "0"))) * D("3")
            direction = "LONG" if score >= D("60") else "SHORT" if score <= D("40") else "WATCH"
            scored.append(
                CoinScore(
                    symbol=str(c["symbol"]),
                    direction=direction,
                    score=int(max(D("0"), min(D("100"), score))),
                    reasoning="quant_score",
                )
            )
        return sorted(scored, key=lambda s: s.score, reverse=True)
