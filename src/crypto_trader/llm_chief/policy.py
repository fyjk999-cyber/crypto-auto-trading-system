"""Canonical LLM policy — the single source of truth for model + reasoning effort.

Why this module exists
----------------------
Reasoning effort was previously defaulted ad hoc at each call site
(``reasoning_effort="low"`` appeared as a provider default AND as an explicit
argument on the Chief Trader's real trading decision). A provider default is the
wrong place for a trading decision's reasoning budget: any new call site silently
inherited "low", and there was no single place to audit what the trading path
actually requests.

So every reasoning parameter now comes from here, keyed by OPERATION, and the
provider's own defaults follow the canonical policy too. No caller is allowed to
hard-code "low" for a real trading decision.

This module deliberately contains no thresholds, no strategy parameters and no
risk logic — it only answers "which model, how much thinking".
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: The only model the trading system may call.
CANONICAL_TRADING_MODEL = "deepseek-flash"

#: Models that must never be selected. Kept explicit (rather than merely absent
#: from the allow-list) so the failure message names the offending value.
FORBIDDEN_MODELS = frozenset(
    {
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v4-pro",
        "deepseek-flash-high",
    }
)

THINKING_ENABLED = True
THINKING_DISABLED = False

REASONING_HIGH = "high"
REASONING_LOW = "low"

#: There is exactly one model. A fallback would mean an unverified model could
#: end up making trade decisions.
NO_FALLBACK_MODEL = True

# ---- operations -----------------------------------------------------------

OPERATION_TRADING_DECISION = "trading_decision"
#: Position review / HOLD / REDUCE / EXIT go through the SAME operation as the
#: entry decision (`ChiefTraderEngine.decide`). Named here explicitly so the
#: requirement is auditable and so a future split cannot silently drop to "low".
OPERATION_POSITION_DECISION = "position_decision"
OPERATION_GROWTH_REVIEW = "growth_review"
OPERATION_STRATEGY_REASONING = "strategy_reasoning"
#: Pure tool routing: intentionally allowed to skip hidden reasoning.
OPERATION_TOOL_SELECTION = "tool_selection"
OPERATION_HEALTH_PROBE = "health_probe"
OPERATION_COMPLETION = "completion"
OPERATION_IMPLEMENTATION = "implementation"


class ForbiddenModelError(ValueError):
    """Raised when a model outside the canonical allow-list is requested.

    Fails CLOSED: an unknown/forbidden model is never silently swapped for the
    canonical one, because a silent swap would hide a misconfiguration that
    changes the reasoning quality behind real trade decisions.
    """


@dataclass(frozen=True, slots=True)
class OperationPolicy:
    operation: str
    thinking: bool
    reasoning_effort: str


#: Operations that make or materially inform real trading decisions.
_TRADING_CRITICAL = frozenset(
    {
        OPERATION_TRADING_DECISION,
        OPERATION_POSITION_DECISION,
    }
)

#: Offline/research reasoning that still benefits from full effort.
_REASONING_OPERATIONS = frozenset(
    {
        OPERATION_GROWTH_REVIEW,
        OPERATION_STRATEGY_REASONING,
    }
)

def policy_for(operation: str) -> OperationPolicy:
    """Resolve the canonical policy for one operation.

    Unknown operations default to thinking DISABLED: a new operation must opt in
    to hidden reasoning rather than inherit a trading-grade budget by accident.
    """
    name = str(operation or OPERATION_COMPLETION)
    if name in _TRADING_CRITICAL or name in _REASONING_OPERATIONS:
        return OperationPolicy(name, THINKING_ENABLED, REASONING_HIGH)
    if name == OPERATION_TOOL_SELECTION:
        return OperationPolicy(name, THINKING_DISABLED, REASONING_LOW)
    return OperationPolicy(name, THINKING_DISABLED, REASONING_LOW)


def thinking_for(operation: str) -> bool:
    return policy_for(operation).thinking


def reasoning_effort_for(operation: str) -> str:
    return policy_for(operation).reasoning_effort


def canonical_model() -> str:
    """The configured model name.

    ``LLM_MODEL`` is honoured only when it names a permitted model; anything else
    (including a forbidden name) raises rather than degrading quietly.
    """
    requested = (os.environ.get("LLM_MODEL") or "").strip() or CANONICAL_TRADING_MODEL
    return validate_model(requested)


def validate_model(model: str | None) -> str:
    """Return the model if permitted, else raise ``ForbiddenModelError``."""
    candidate = (str(model).strip() if model is not None else "") or CANONICAL_TRADING_MODEL
    if candidate in FORBIDDEN_MODELS:
        raise ForbiddenModelError(
            f"model {candidate!r} is forbidden by the canonical LLM policy; "
            f"only {CANONICAL_TRADING_MODEL!r} may be used"
        )
    if candidate != CANONICAL_TRADING_MODEL:
        raise ForbiddenModelError(
            f"unknown model {candidate!r}; the canonical policy permits only "
            f"{CANONICAL_TRADING_MODEL!r}"
        )
    return candidate


def effective_policy(operation: str) -> dict:
    """Runtime-visible facts. NEVER contains credential material."""
    policy = policy_for(operation)
    model = canonical_model()
    return {
        "provider": "deepseek",
        "configured_model": model,
        "effective_model": model,
        "thinking": policy.thinking,
        "reasoning_effort": policy.reasoning_effort,
        "operation": policy.operation,
        "no_fallback_model": NO_FALLBACK_MODEL,
    }


__all__ = [
    "CANONICAL_TRADING_MODEL",
    "FORBIDDEN_MODELS",
    "ForbiddenModelError",
    "NO_FALLBACK_MODEL",
    "OPERATION_COMPLETION",
    "OPERATION_GROWTH_REVIEW",
    "OPERATION_HEALTH_PROBE",
    "OPERATION_IMPLEMENTATION",
    "OPERATION_POSITION_DECISION",
    "OPERATION_STRATEGY_REASONING",
    "OPERATION_TOOL_SELECTION",
    "OPERATION_TRADING_DECISION",
    "OperationPolicy",
    "REASONING_HIGH",
    "REASONING_LOW",
    "canonical_model",
    "effective_policy",
    "policy_for",
    "reasoning_effort_for",
    "thinking_for",
    "validate_model",
]
