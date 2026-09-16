"""Fail-closed configuration and non-secret metrics for legacy LLM calls.

``LEGACY_LLM_ENABLED`` protects only the original pre-Low-Risk-V2 clients.
The Low-Risk V2 ``llm_chief`` provider deliberately has a different boundary
and is not read or modified here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

LEGACY_LLM_DISABLED_BY_CONFIG = "LLM_DISABLED_BY_CONFIG"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def legacy_llm_enabled(value: bool | None = None) -> bool:
    """Resolve the legacy-only switch without reading provider credentials."""

    if value is not None:
        return value
    raw = os.environ.get("LEGACY_LLM_ENABLED")
    if raw is None:
        # Preserve historic behavior until an operator opts into isolation.
        return True
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    # Invalid safety configuration must not accidentally disable an existing
    # installation. Settings validation is responsible for explicit config.
    return True


@dataclass
class LegacyLLMInvocationTracker:
    """In-memory proof that the guarded legacy boundary made no network call.

    The tracker intentionally carries caller labels and counts only.  It never
    retains prompts, headers, response bodies, or secret material.
    """

    provider_calls: int = 0
    disabled_calls: int = 0
    callers: dict[str, int] = field(default_factory=dict)
    providers: dict[str, int] = field(default_factory=dict)

    def record_disabled(self, caller: str) -> None:
        self.disabled_calls += 1
        self.callers[caller] = self.callers.get(caller, 0) + 1

    def record_provider_call(self, caller: str, *, provider: str) -> None:
        self.provider_calls += 1
        self.callers[caller] = self.callers.get(caller, 0) + 1
        normalized = provider.strip().lower() or "unknown"
        self.providers[normalized] = self.providers.get(normalized, 0) + 1

    def snapshot(self) -> dict[str, object]:
        return {
            "provider_calls": self.provider_calls,
            "llm_provider_calls": self.provider_calls,
            "deepseek_requests": self.providers.get("deepseek", 0),
            "glm_requests": self.providers.get("glm", 0),
            "other_llm_requests": sum(
                calls
                for name, calls in self.providers.items()
                if name not in {"deepseek", "glm"}
            ),
            "disabled_calls": self.disabled_calls,
            "callers": dict(self.callers),
            "providers": dict(self.providers),
        }
