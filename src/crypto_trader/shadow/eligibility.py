"""Shadow eligibility gate — which NO_TRADE decisions deserve a counterfactual.

Only a DECISION-level abstention is interesting: the strategy looked at good
data and chose to stand aside. A NO_TRADE caused by a system condition
(market data missing, LLM budget spent, reconciliation halted, provider down,
DB error) is NOT a strategy opinion and must never produce a shadow candidate —
learning from an infrastructure outage would teach the wrong lesson.

Pure, deterministic, no I/O and no LLM: the gate only classifies facts the
caller already has.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Actions that abstained. LONG/SHORT already became real trades; HOLD/REDUCE/
#: EXIT belong to position management, which is a different lifecycle.
SHADOW_ELIGIBLE_ACTIONS = frozenset({"WAIT", "NO_TRADE"})

#: ``reason_codes`` (and thesis) markers that mean "not a strategy judgement".
#: Any hit makes the decision shadow-INELIGIBLE: these describe the system, not
#: the strategy.
SYSTEM_ERROR_MARKERS = (
    "SKIPPED_BUDGET",
    "ENTRY_BUDGET_EXHAUSTED",
    "POSITION_MANAGEMENT_BUDGET_EXHAUSTED",
    "LLM_UNAVAILABLE",
    "PROVIDER_DOWN",
    "PROVIDER_TIMEOUT",
    "MARKET_DATA_UNAVAILABLE",
    "DATA_QUALITY",
    "RECONCILIATION",
    "RECONCILIATION_HALTED",
    "DB_ERROR",
    "PERSISTENCE",
    "EXECUTION_SYSTEM_ERROR",
    "FAIL_CLOSED",
    "TIMEOUT",
)

#: Reason codes that represent a genuine strategy abstention. Presence of at
#: least one (or a non-empty thesis) is required: a bare NO_TRADE with no stated
#: hypothesis has nothing to evaluate.
STRATEGY_ABSTENTION_MARKERS = (
    "SIGNAL_TOO_WEAK",
    "WEAK_SIGNAL",
    "CONFIRMATION_INSUFFICIENT",
    "INSUFFICIENT_CONFIRMATION",
    "ENTRY_THRESHOLD",
    "THRESHOLD_NOT_MET",
    "APPLICABILITY",
    "REGIME",
    "LOW_CONVICTION",
    "NO_EDGE",
    "RANGE",
    "UNCERTAIN",
)

REASON_ELIGIBLE = "ELIGIBLE"
REASON_NOT_ABSTENTION = "NOT_AN_ABSTENTION"
REASON_SYSTEM_ERROR = "SYSTEM_ERROR_NOT_A_STRATEGY_JUDGEMENT"
REASON_NO_HYPOTHESIS = "NO_STRATEGY_HYPOTHESIS"
REASON_MARKET_DATA_NOT_GOOD = "MARKET_DATA_QUALITY_NOT_GOOD"
REASON_NO_REFERENCE_PRICE = "NO_REFERENCE_PRICE"
REASON_NOT_PERSISTED = "DECISION_NOT_PERSISTED"
REASON_UNKNOWN_REGIME = "REGIME_NOT_USABLE"


@dataclass(frozen=True, slots=True)
class ShadowEligibility:
    """Verdict plus the single reason it was reached (auditable, no guessing)."""

    eligible: bool
    reason: str
    direction_hypothesis: str | None = None
    matched_markers: tuple[str, ...] = field(default_factory=tuple)


def _flatten(*parts) -> str:
    out: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (list, tuple, set, frozenset)):
            out.extend(str(x) for x in part)
        else:
            out.append(str(part))
    return " ".join(out).upper()


def shadow_eligibility(
    *,
    action: str,
    reason_codes=None,
    thesis: str | None = None,
    market_data_quality: str | None = None,
    reference_price=None,
    decision_persisted: bool = False,
    market_regime: str | None = None,
) -> ShadowEligibility:
    """Decide whether a committed decision may become a shadow candidate.

    Order matters: system-error disqualification is checked BEFORE the
    abstention check, so a ``FAIL_CLOSED`` that happens to carry ``NO_TRADE``
    never slips through as a strategy opinion.
    """
    text = _flatten(reason_codes, thesis, action)

    # 1. Not an abstention at all.
    if str(action).upper() not in SHADOW_ELIGIBLE_ACTIONS:
        return ShadowEligibility(False, REASON_NOT_ABSTENTION)

    # 2. System condition masquerading as an abstention — disqualify FIRST.
    hits = tuple(m for m in SYSTEM_ERROR_MARKERS if m in text)
    if hits:
        return ShadowEligibility(
            False, REASON_SYSTEM_ERROR, matched_markers=hits
        )

    # 3. Must be a real strategy judgement with a stated hypothesis.
    strategy_hits = tuple(m for m in STRATEGY_ABSTENTION_MARKERS if m in text)
    has_thesis = bool((thesis or "").strip())
    if not strategy_hits and not has_thesis:
        return ShadowEligibility(False, REASON_NO_HYPOTHESIS)

    # 4. Inputs must be trustworthy — refuse to learn from bad data.
    if str(market_data_quality or "").upper() not in ("GOOD", "HEALTHY"):
        return ShadowEligibility(False, REASON_MARKET_DATA_NOT_GOOD)

    # 5. A frozen reference price is required (no look-ahead, no later picking).
    if reference_price is None:
        return ShadowEligibility(False, REASON_NO_REFERENCE_PRICE)
    try:
        if float(reference_price) <= 0:
            return ShadowEligibility(False, REASON_NO_REFERENCE_PRICE)
    except (TypeError, ValueError):
        return ShadowEligibility(False, REASON_NO_REFERENCE_PRICE)

    # 6. Only committed decisions are observable.
    if not decision_persisted:
        return ShadowEligibility(False, REASON_NOT_PERSISTED)

    # 7. Regime may be explicitly UNKNOWN-valid, but must be stated.
    regime = str(market_regime or "").strip()
    if not regime:
        return ShadowEligibility(False, REASON_UNKNOWN_REGIME)

    direction = _direction_hypothesis(action, text)
    return ShadowEligibility(
        True,
        REASON_ELIGIBLE,
        direction_hypothesis=direction,
        matched_markers=strategy_hits,
    )


def _direction_hypothesis(action: str, text: str) -> str:
    """The side the abstention was weighing.

    ``action`` is WAIT/NO_TRADE so it cannot carry the side; the hypothesis is
    taken from the stated reasoning. Defaults to ``NONE`` when the decision
    genuinely expressed no directional lean — that is a valid, useful sample
    (a pure "no opportunity" observation) and must not be invented as LONG.
    """
    if "LONG" in text and "SHORT" not in text:
        return "LONG"
    if "SHORT" in text and "LONG" not in text:
        return "SHORT"
    return "NONE"
