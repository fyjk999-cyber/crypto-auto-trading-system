"""AI historical market memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.ai_memory.embedding import embed_market_state
from crypto_trader.ai_memory.similarity import cosine_similarity


@dataclass
class MarketMemoryRecord:
    symbol: str
    state: dict
    ai_decision: str
    result: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    embedding: tuple[float, ...] = ()


class MarketMemory:
    def __init__(self) -> None:
        self.records: list[MarketMemoryRecord] = []

    def store(
        self, symbol: str, state: dict, ai_decision: str, result: str | None = None
    ) -> MarketMemoryRecord:
        embedding = embed_market_state(state)
        record = MarketMemoryRecord(
            symbol=symbol, state=state, ai_decision=ai_decision, result=result, embedding=embedding
        )
        self.records.append(record)
        return record

    def find_similar(self, symbol: str, state: dict, top_k: int = 3) -> list[MarketMemoryRecord]:
        target = embed_market_state(state)
        candidates = [r for r in self.records if r.symbol == symbol]
        if not candidates:
            return []
        scored = sorted(
            candidates, key=lambda r: cosine_similarity(target, r.embedding), reverse=True
        )
        return scored[:top_k]
