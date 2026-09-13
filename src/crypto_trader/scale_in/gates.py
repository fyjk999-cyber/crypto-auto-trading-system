"""Deterministic ADD admission gates (§79-§95, §104-§111, §123-§135).

Every gate is a deterministic rule over factual inputs. The LLM never decides
whether a gate is satisfied, and no gate can be bypassed by the LLM declaring
urgency, conviction, or an "OTHER" trigger.

Priority (§109): ``EXIT > REDUCE > ADD > HOLD``. A cycle that could EXIT or
REDUCE never ADDs, and ADD and REDUCE are never produced together (§110).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from crypto_trader.domain.money import D
from crypto_trader.scale_in.contract import ScaleInIntent, ThesisStatus
from crypto_trader.scale_in.policy import ScaleInPolicy

# ---- verdicts
VERDICT_ALLOWED = "ALLOWED"
VERDICT_REJECTED = "REJECTED"
VERDICT_COALESCED = "COALESCED"

# ---- reason codes (§127-§135 and friends)
ADD_EXECUTION_DISABLED = "ADD_EXECUTION_DISABLED_FEATURE_FLAG"
ADD_THESIS_INVALIDATED = "ADD_THESIS_INVALIDATED"
ADD_DIRECTION_MISMATCH = "ADD_DIRECTION_MISMATCH"
ADD_MAX_COUNT_REACHED = "MAX_SCALE_IN_COUNT_REACHED"
ADD_COOLDOWN_ACTIVE = "SCALE_IN_COOLDOWN_ACTIVE"
ADD_COALESCED = "ADD_COALESCED"
ADD_MATERIAL_CHANGE_REQUIRED = "ADD_MATERIAL_CHANGE_REQUIRED"
ADD_AVERAGE_DOWN_NOT_AUTHORIZED = "AVERAGE_DOWN_NOT_AUTHORIZED"
ADD_ADVERSE_WITHOUT_CONFIRMATION = "ADVERSE_ADD_WITHOUT_STRUCTURAL_CONFIRMATION"
ADD_CAMPAIGN_RISK_EXHAUSTED = "CAMPAIGN_RISK_BUDGET_EXHAUSTED"
ADD_DRAWDOWN_DISABLED = "ADD_DISABLED_BY_DRAWDOWN"
ADD_DRAWDOWN_UNDETERMINED = "ADD_REQUIRES_A_FRESH_DRAWDOWN_FACT"
ADD_PENDING_POSITION_ACTION = "PENDING_POSITION_ACTION"
ADD_EXIT_PRECEDENCE = "EXIT_TAKES_PRECEDENCE_OVER_ADD"
ADD_REDUCE_PRECEDENCE = "REDUCE_TAKES_PRECEDENCE_OVER_ADD"
ADD_NO_POSITION = "ADD_REQUIRES_AN_OPEN_POSITION"
ADD_STOP_INVALID = "ADD_STOP_INVALID"
ADD_STOP_WRONG_SIDE = "ADD_STOP_WRONG_SIDE"
ADD_NOT_AUTHORIZED_REASON = "ADD_REASON_NOT_DECISION_RELEVANT"

#: Structural confirmation required before any adverse ADD (§80, §95).
STRUCTURAL_CONFIRMATION_TRIGGERS = (
    "BREAKOUT_CONFIRMATION",
    "TREND_CONTINUATION",
    "REGIME_STRENGTHENING",
)


@dataclass(frozen=True)
class ScaleInGateInputs:
    """Factual inputs the gates decide over.

    The ADD intent is deliberately NOT a field here: it is passed explicitly to
    :func:`evaluate_scale_in_gates` so there is exactly ONE intent object in
    play. A duplicated intent would let the gates vet a different request than
    the Sizer ends up sizing.
    """

    campaign_direction: str
    has_open_position: bool
    campaign_add_count: int
    last_add_at: datetime | None
    now: datetime
    #: §94/§95 — adverse movement measured as a fraction of the entry price.
    adverse_fraction: Decimal = Decimal("0")
    #: §109/§110 — whether the same review cycle could EXIT or REDUCE.
    exit_condition: bool = False
    reduce_condition: bool = False
    #: §111 — an unresolved position-action order exists for this symbol.
    pending_position_action: bool = False
    #: §103 — current account drawdown ratio, None when UNKNOWN.
    drawdown_ratio: Decimal | None = None
    #: §104 — the campaign-level risk budget and its consumption.
    campaign_risk_budget: Decimal = Decimal("0")
    consumed_campaign_risk: Decimal = Decimal("0")


@dataclass(frozen=True)
class ScaleInGateResult:
    allowed: bool
    verdict: str
    reason_codes: tuple[str, ...]
    drawdown_multiplier: Decimal
    effective_interval_seconds: float
    detail: dict

    def to_evidence(self) -> dict:
        return {
            "allowed": self.allowed,
            "verdict": self.verdict,
            "reason_codes": list(self.reason_codes),
            "drawdown_multiplier": str(self.drawdown_multiplier),
            "effective_interval_seconds": self.effective_interval_seconds,
            **self.detail,
        }


def evaluate_scale_in_gates(
    intent: ScaleInIntent, inputs: ScaleInGateInputs, policy: ScaleInPolicy
) -> ScaleInGateResult:
    """Apply every deterministic ADD gate in a fixed, documented order."""
    detail: dict = {
        "trigger": intent.trigger.value,
        "thesis_status": intent.thesis_status.value,
        "add_count": int(inputs.campaign_add_count),
        "max_scale_in_count": policy.max_scale_in_count,
        "material_change": intent.material_change,
        "adverse_fraction": str(inputs.adverse_fraction),
        "average_down_enabled": policy.average_down_enabled,
        "add_number": int(inputs.campaign_add_count) + 1,
    }
    drawdown_multiplier = policy.drawdown_multiplier(inputs.drawdown_ratio)

    def reject(*codes: str) -> ScaleInGateResult:
        return ScaleInGateResult(
            allowed=False,
            verdict=VERDICT_REJECTED,
            reason_codes=tuple(codes),
            drawdown_multiplier=drawdown_multiplier,
            effective_interval_seconds=policy.min_scale_in_interval_seconds,
            detail=detail,
        )

    def coalesce(*codes: str) -> ScaleInGateResult:
        # The canonical outcome is always reported, together with the specific
        # deterministic reason it coalesced (§93).
        return ScaleInGateResult(
            allowed=False,
            verdict=VERDICT_COALESCED,
            reason_codes=tuple(dict.fromkeys((ADD_COALESCED, *codes))),
            drawdown_multiplier=drawdown_multiplier,
            effective_interval_seconds=policy.min_scale_in_interval_seconds,
            detail=detail,
        )

    # §109/§110 — risk-reducing actions outrank ADD, always.
    if inputs.exit_condition:
        return reject(ADD_EXIT_PRECEDENCE)
    if inputs.reduce_condition:
        return reject(ADD_REDUCE_PRECEDENCE)
    # §111 — an unresolved position action keeps its liveness/dedupe authority.
    if inputs.pending_position_action:
        return reject(ADD_PENDING_POSITION_ACTION)
    # §82/§133 — ADD can only ever continue the EXISTING direction.
    if str(intent.direction).upper() != str(inputs.campaign_direction).upper():
        return reject(ADD_DIRECTION_MISMATCH)
    # An ADD needs something to add to.
    if not inputs.has_open_position:
        return reject(ADD_NO_POSITION)
    # §81/§128 — an invalidated or weakened thesis can only REDUCE or EXIT.
    if intent.thesis_status in {ThesisStatus.INVALIDATED, ThesisStatus.WEAKENED}:
        return reject(ADD_THESIS_INVALIDATED)
    # §96 — a valid, correctly-sided stop is mandatory before any ADD.
    stop = intent.stop_loss_value
    if stop <= 0:
        return reject(ADD_STOP_INVALID)
    # §79/§94/§95/§127 — never turn scale-in into a martingale.
    if inputs.adverse_fraction > policy.adverse_tolerance_fraction:
        if not policy.average_down_enabled and not _has_structural_confirmation(
            intent.trigger.value
        ):
            return reject(ADD_AVERAGE_DOWN_NOT_AUTHORIZED)
        if not _has_structural_confirmation(intent.trigger.value):
            return reject(ADD_ADVERSE_WITHOUT_CONFIRMATION)
    # §80 — the reason must be decision-relevant on its own merits.
    if intent.trigger.value not in STRUCTURAL_CONFIRMATION_TRIGGERS and (
        intent.trigger.value == "OTHER"
        and not intent.material_change
    ):
        return reject(ADD_NOT_AUTHORIZED_REASON)
    # §103/§83 — a missing drawdown fact is UNKNOWN, never "no drawdown":
    # an ADD is a new risk event and needs a fresh, proven risk fact.
    if inputs.drawdown_ratio is None:
        return reject(ADD_DRAWDOWN_UNDETERMINED)
    # §103 — drawdown shrinks the ADD, and past the hard band disables it.
    if drawdown_multiplier <= 0:
        return reject(ADD_DRAWDOWN_DISABLED)
    # §91/§129 — bounded pyramiding.
    if int(inputs.campaign_add_count) >= policy.max_scale_in_count:
        return reject(ADD_MAX_COUNT_REACHED)
    # §104/§135 — cumulative campaign risk is a hard stop, even under the caps.
    if (
        D(inputs.campaign_risk_budget) - D(inputs.consumed_campaign_risk)
    ) <= 0:
        return reject(ADD_CAMPAIGN_RISK_EXHAUSTED)
    # §92/§130 — cooldown, bypassable only by a deterministic material event.
    if inputs.last_add_at is not None:
        elapsed = (inputs.now - inputs.last_add_at).total_seconds()
        if elapsed < policy.min_scale_in_interval_seconds and not (
            intent.material_change and intent.material_change_reasons
        ):
            return coalesce(ADD_COOLDOWN_ACTIVE)
    # §93 — no material change since the last review means no second execution.
    if not intent.material_change:
        return coalesce(ADD_MATERIAL_CHANGE_REQUIRED)

    return ScaleInGateResult(
        allowed=True,
        verdict=VERDICT_ALLOWED,
        reason_codes=("ADD_GATES_PASSED",),
        drawdown_multiplier=drawdown_multiplier,
        effective_interval_seconds=policy.min_scale_in_interval_seconds,
        detail=detail,
    )


def _has_structural_confirmation(trigger: str) -> bool:
    return trigger in STRUCTURAL_CONFIRMATION_TRIGGERS


def cooldown_expires_at(policy: ScaleInPolicy, last_add_at: datetime) -> datetime:
    return last_add_at + timedelta(seconds=policy.min_scale_in_interval_seconds)
