"""LowRisk-only episodic-memory read port. No backend, index, embedder or writer.

Feature remains off until separately authorized. Results are untrusted evidence,
never direction, sizing, Risk, execution or a substitute for DeepSeek authority.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

MEMORY_SCHEMA_VERSION = "symbol-episodic-memory-v1"
VERSION_FIELDS = (
    "strategy_version",
    "factor_version",
    "model_version",
    "source_sha",
    "memory_schema_version",
)
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9_-]{0,39}\Z")


@dataclass(frozen=True)
class MemoryRequest:
    symbol: str
    as_of: datetime
    provenance: dict[str, str | None]
    limit: int = 5

    @property
    def namespace(self) -> str:
        if not _SYMBOL.fullmatch(self.symbol):
            raise ValueError("INVALID_MEMORY_SYMBOL")
        return "lowrisk/" + self.symbol


class SymbolMemoryReadPort(Protocol):
    def retrieve(self, request: MemoryRequest) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class MemoryEvidence:
    status: str
    namespace: str
    records: tuple[dict[str, Any], ...] = ()
    reason: str | None = None
    provenance: dict[str, str | None] = field(default_factory=dict)

    def prompt_block(self) -> str:
        # Serialize as quoted data, not instructions. Never supply an action field.
        return "SymbolMemoryEvidenceOnly: " + json.dumps(
            {
                "status": self.status,
                "namespace": self.namespace,
                "records": self.records,
                "provenance": self.provenance,
                "authority": "NONE",
                "reason": self.reason,
            },
            sort_keys=True,
        )


class LowRiskSymbolMemoryAdapter:
    def __init__(self, port: SymbolMemoryReadPort | None = None, *, enabled: bool = False):
        self.port = port
        self.enabled = enabled
        self.retrieval_count = 0
        self.unavailable_count = 0

    def retrieve(self, request: MemoryRequest) -> MemoryEvidence:
        namespace = request.namespace
        provenance = {key: request.provenance.get(key) for key in VERSION_FIELDS}

        def unavailable(reason: str) -> MemoryEvidence:
            self.unavailable_count += 1
            return MemoryEvidence(
                "MEMORY_UNAVAILABLE", namespace, reason=reason, provenance=provenance
            )

        if not self.enabled or self.port is None:
            return unavailable("DISABLED" if not self.enabled else "NO_READ_PORT")
        if request.as_of.tzinfo is None or not 1 <= request.limit <= 20:
            return unavailable("INVALID_REQUEST")
        if any(not value for value in provenance.values()):
            return unavailable("PROVENANCE_MISSING")
        if provenance["memory_schema_version"] != MEMORY_SCHEMA_VERSION:
            return unavailable("SCHEMA_INCOMPATIBLE")
        try:
            self.retrieval_count += 1
            rows = self.port.retrieve(request)
            if not isinstance(rows, list) or len(rows) > request.limit:
                return unavailable("INVALID_RESPONSE")
            output = []
            for row in rows:
                if row.get("namespace") != namespace or row.get("symbol") != request.symbol:
                    return unavailable("CROSS_NAMESPACE_REJECTED")
                if any(row.get(key) != value for key, value in provenance.items()):
                    return unavailable("VERSION_MISMATCH")
                known_at = datetime.fromisoformat(row["factual_as_of"])
                closed_at = datetime.fromisoformat(row["closed_at"])
                if (
                    known_at.tzinfo is None
                    or closed_at.tzinfo is None
                    or known_at > request.as_of
                    or closed_at > request.as_of
                    or not row.get("episode_id")
                    or row.get("factual") is not True
                ):
                    return unavailable("NONFACTUAL_OR_FUTURE_MEMORY")
                # Ignore provider-specific/action payloads. Preserve supplied facts
                # and exact IDs, including negative outcomes, without inventing them.
                output.append(
                    {
                        key: row[key]
                        for key in (
                            "episode_id",
                            "namespace",
                            "symbol",
                            "factual_as_of",
                            "closed_at",
                            "net_pnl",
                            "fees",
                            "funding",
                            "review_summary",
                            "retrieval_score",
                            *VERSION_FIELDS,
                        )
                        if key in row
                    }
                )
            return MemoryEvidence(
                "AVAILABLE" if output else "NO_RELEVANT_PRIOR_EXPERIENCE",
                namespace,
                tuple(output),
                provenance=provenance,
            )
        except Exception:
            # No backend exception string: it can contain credentials/paths.
            return unavailable("READ_PORT_FAILURE")
