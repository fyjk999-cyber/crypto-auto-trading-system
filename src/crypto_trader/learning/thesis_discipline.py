"""Growth V2 thesis-rationalization detector (Phase 5).

SPEC loss discipline: a losing position may not keep the original thesis while
its Base Exit is moved further away just to avoid admitting failure. Valid paths
are REDUCE/CLOSE, a genuinely revised thesis with NEW justification, or an
independent opposite thesis (hedge/reverse).

Learning/observability only — this detector never trades and never gates Risk
or Execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RATIONALE_TOKENS = (
    "new evidence",
    "independent thesis",
    "model state change",
    "regime change",
    "invalidated by",
    "news",
    "new setup",
    "new justification",
)


@dataclass
class RationalizationCheck:
    verdict: str
    flags: list[str] = field(default_factory=list)
    license_to_modify: bool = False
    authority: str = "LEARNING_ONLY"
    is_order: bool = False


def _token_overlap(a: str, b: str) -> float:
    left = {token for token in a.lower().split() if token}
    right = {token for token in b.lower().split() if token}
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _base_exit_worse(
    *,
    direction: str,
    original_base_exit: float | None,
    new_base_exit: float | None,
    tolerance: float,
) -> bool:
    if original_base_exit is None or new_base_exit is None:
        return False
    if direction.upper() == "LONG":
        return new_base_exit < original_base_exit - tolerance
    return new_base_exit > original_base_exit + tolerance


def _invalidation_weakened(
    *,
    direction: str,
    original_invalidation: float | None,
    new_invalidation: float | None,
    entry_price: float,
    tolerance: float,
) -> bool:
    if original_invalidation is None or new_invalidation is None:
        return False
    if direction.upper() == "LONG":
        return new_invalidation < original_invalidation - tolerance
    return new_invalidation > original_invalidation + tolerance


def check_thesis_rationalization(
    *,
    direction: str,
    entry_price: float,
    current_price: float,
    original_thesis: str,
    new_thesis: str,
    original_base_exit: float | None,
    new_base_exit: float | None,
    original_invalidation: float | None = None,
    new_invalidation: float | None = None,
    tolerance: float = 1e-9,
) -> RationalizationCheck:
    """Detect target-moving after a loss without a new factual justification."""
    move = current_price - entry_price
    losing = move < 0 if direction.upper() == "LONG" else move > 0
    flags: list[str] = []
    if _base_exit_worse(
        direction=direction,
        original_base_exit=original_base_exit,
        new_base_exit=new_base_exit,
        tolerance=tolerance,
    ):
        flags.append("BASE_EXIT_MOVED_FARTHER_FROM_ENTRY")
    if _invalidation_weakened(
        direction=direction,
        original_invalidation=original_invalidation,
        new_invalidation=new_invalidation,
        entry_price=entry_price,
        tolerance=tolerance,
    ):
        flags.append("INVALIDATION_WEAKENED")

    thesis_changed = _token_overlap(original_thesis, new_thesis) < 0.6
    has_new_justification = any(token in new_thesis.lower() for token in RATIONALE_TOKENS) or (
        thesis_changed and bool(new_thesis.strip())
    )

    if not losing:
        return RationalizationCheck(verdict="DISCIPLINE_OK", flags=flags)
    if flags and not has_new_justification:
        flags.append("THESIS_UNCHANGED_AFTER_LOSS")
        return RationalizationCheck(verdict="POSSIBLE_THESIS_RATIONALIZATION", flags=flags)
    if has_new_justification:
        return RationalizationCheck(
            verdict="THESIS_REVISED_WITH_NEW_JUSTIFICATION",
            flags=flags,
            license_to_modify=True,
        )
    return RationalizationCheck(verdict="DISCIPLINE_OK", flags=flags)
