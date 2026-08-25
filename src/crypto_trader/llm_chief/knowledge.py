"""LLM Knowledge Base: theory/tools, versioned. Separate from experience memory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class StrategyCard:
    strategy_id: str
    name: str
    strategy_family: str
    description: str
    ideal_regimes: list[str]
    bad_regimes: list[str]
    required_evidence: list[str]
    entry_logic: str
    exit_logic: str
    invalidation_logic: str
    position_sizing_guidance: str
    leverage_guidance: str
    expected_holding_period: str
    known_failure_modes: list[str]
    evidence_quality: str
    version: str
    status: str = "ACTIVE"


@dataclass
class ToolRecord:
    tool_id: str
    tool_name: str
    description: str
    when_to_use: str
    when_not_to_use: str
    latency_class: str
    cost_class: str
    version: str


class KnowledgeBase:
    def __init__(self) -> None:
        self.strategy_cards: dict[str, StrategyCard] = {}
        self.tool_catalog: dict[str, ToolRecord] = {}
        self.documents: dict[str, dict] = {}

    def add_strategy(self, card: StrategyCard) -> None:
        self.strategy_cards[card.strategy_id] = card

    def add_tool(self, tool: ToolRecord) -> None:
        self.tool_catalog[tool.tool_id] = tool

    def add_document(
        self, doc_id: str, title: str, content: str, tags: list[str], version: str
    ) -> None:
        self.documents[doc_id] = {
            "title": title,
            "content": content,
            "tags": tags,
            "version": version,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def retrieve(self, query_tags: list[str], top_k: int = 5) -> list[dict]:
        scored = []
        for doc_id, doc in self.documents.items():
            overlap = len(set(query_tags) & set(doc["tags"]))
            if overlap > 0:
                scored.append(
                    {
                        "id": doc_id,
                        "title": doc["title"],
                        "relevance": overlap / max(len(set(doc["tags"])), 1),
                        "version": doc["version"],
                        "tags": doc["tags"],
                    }
                )
        return sorted(scored, key=lambda d: d["relevance"], reverse=True)[:top_k]
