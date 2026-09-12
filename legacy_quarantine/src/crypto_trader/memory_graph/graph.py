"""Relational memory graph."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MemoryNode:
    node_id: str
    kind: str
    value: str


@dataclass
class MemoryEdge:
    source: str
    relation: str
    target: str


class MemoryGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, MemoryNode] = {}
        self.edges: list[MemoryEdge] = []

    def add_node(self, node_id: str, kind: str, value: str) -> None:
        self.nodes[node_id] = MemoryNode(node_id, kind, value)

    def add_edge(self, source: str, relation: str, target: str) -> None:
        self.edges.append(MemoryEdge(source, relation, target))

    def query(self, node_id: str, relation: str) -> list[str]:
        return [e.target for e in self.edges if e.source == node_id and e.relation == relation]
