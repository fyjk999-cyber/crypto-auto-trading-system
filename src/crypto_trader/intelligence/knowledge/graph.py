"""Market knowledge graph (regime -> factor -> research -> outcome)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KnowledgeRelation:
    entity_a: str
    relation: str
    entity_b: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "entity_a": self.entity_a,
            "relation": self.relation,
            "entity_b": self.entity_b,
            "metadata": self.metadata,
        }


class KnowledgeGraph:
    def __init__(self) -> None:
        self.relations: list[KnowledgeRelation] = []

    def add(
        self, entity_a: str, relation: str, entity_b: str, metadata: dict | None = None
    ) -> None:
        self.relations.append(KnowledgeRelation(entity_a, relation, entity_b, metadata or {}))

    def query(self, question: str) -> list[dict]:
        question_lower = question.lower()
        matches = []
        for relation in self.relations:
            text = f"{relation.entity_a} {relation.relation} {relation.entity_b}".lower()
            if any(word in text for word in question_lower.split()):
                matches.append(relation.to_dict())
        return matches
