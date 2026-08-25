"""Vector memory schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class MemoryVector:
    id: str
    object_type: str
    object_id: str
    content_hash: str
    embedding: list[float]
    metadata: dict
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    version: int = 1
