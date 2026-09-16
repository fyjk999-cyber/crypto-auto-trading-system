"""Legacy LLM isolation boundary.

This package is deliberately limited to the pre-Low-Risk-V2 call paths.  It
must never be imported by the canonical ``llm_chief`` provider path.
"""

from crypto_trader.legacy_llm.isolation import (
    LEGACY_LLM_DISABLED_BY_CONFIG,
    LegacyLLMInvocationTracker,
    legacy_llm_enabled,
)

__all__ = [
    "LEGACY_LLM_DISABLED_BY_CONFIG",
    "LegacyLLMInvocationTracker",
    "legacy_llm_enabled",
]
