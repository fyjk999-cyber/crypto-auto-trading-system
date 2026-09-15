"""Phase 4D hedge leg contract tests (SPEC: independent opposite leg only)."""

from __future__ import annotations

from crypto_trader.execution.hedge_legs import (
    HedgeLegContract,
    HedgeLegRegistry,
    LegKind,
    validate_hedge_leg,
)

LONG = HedgeLegContract(
    leg_id="leg-long",
    symbol="BTCUSDT",
    side="LONG",
    kind=LegKind.ENTRY,
    strategy="BREAKOUT",
    thesis="breakout continuation over 105",
    base_exit={"type": "PRICE", "trigger": ">=110"},
    invalidation="close below 98",
    evidence_families=["trend", "orderflow"],
    reason="momentum entry",
)


def _short(**overrides) -> HedgeLegContract:
    values = dict(
        leg_id="leg-short",
        symbol="BTCUSDT",
        side="SHORT",
        kind=LegKind.HEDGE,
        strategy="MEAN_REVERT",
        thesis="range rejection at 112 with exhaustion",
        base_exit={"type": "PRICE", "trigger": "<=104"},
        invalidation="acceptance above 115",
        evidence_families=["mean_reversion", "orderbook"],
        reason="independent reversal thesis",
    )
    values.update(overrides)
    return HedgeLegContract(**values)


def test_independent_opposite_leg_is_allowed() -> None:
    result = validate_hedge_leg(_short(), [LONG])
    assert result.allowed is True
    assert result.violations == []
    assert result.authority == "NEW_RISK_REQUIRES_CORE_LLM"
    assert result.is_order is False


def test_loss_mitigation_only_reason_is_rejected() -> None:
    contract = _short(reason="reduce loss on the original LONG")
    result = validate_hedge_leg(contract, [LONG])
    assert result.allowed is False
    assert "ILLEGAL_HEDGE_REASON_LOSS_MITIGATION_ONLY" in result.violations


def test_same_strategy_or_thesis_is_not_independent() -> None:
    same_strategy = _short(strategy="BREAKOUT")
    result = validate_hedge_leg(same_strategy, [LONG])
    assert result.allowed is False
    assert "SAME_STRATEGY_NOT_INDEPENDENT" in result.violations

    same_thesis = _short(thesis=LONG.thesis)
    result = validate_hedge_leg(same_thesis, [LONG])
    assert result.allowed is False
    assert "DUPLICATE_THESIS_NOT_INDEPENDENT" in result.violations


def test_missing_required_fields_are_rejected() -> None:
    contract = _short(base_exit=None, invalidation="", evidence_families=[])
    result = validate_hedge_leg(contract, [])
    assert result.allowed is False
    assert "MISSING_BASE_EXIT" in result.violations
    assert "MISSING_INVALIDATION" in result.violations
    assert "MISSING_EVIDENCE_FAMILIES" in result.violations


def test_same_side_add_does_not_require_hedge_independence() -> None:
    add = HedgeLegContract(
        leg_id="leg-add",
        symbol="BTCUSDT",
        side="LONG",
        kind=LegKind.ADD,
        strategy="BREAKOUT",
        thesis=LONG.thesis,
        base_exit={"type": "PRICE", "trigger": ">=110"},
        invalidation="close below 98",
        evidence_families=["trend"],
        reason="pyramid on strength",
    )
    result = validate_hedge_leg(add, [LONG])
    assert result.allowed is True
    assert result.violations == []


def test_reverse_requires_source_leg() -> None:
    reverse = _short(kind=LegKind.REVERSE, reverse_of=None)
    result = validate_hedge_leg(reverse, [LONG])
    assert result.allowed is False
    assert "REVERSE_MISSING_SOURCE_LEG" in result.violations


def test_registry_tracks_both_sides_and_rejects_illegal_hedge() -> None:
    registry = HedgeLegRegistry()
    assert registry.register(LONG).allowed is True
    assert registry.has_opposite("BTCUSDT", "LONG") is False

    rejected = registry.register(_short(reason="offset loss"))
    assert rejected.allowed is False
    assert registry.has_opposite("BTCUSDT", "LONG") is False

    assert registry.register(_short()).allowed is True
    assert registry.has_opposite("BTCUSDT", "LONG") is True
    snapshot = registry.snapshot("BTCUSDT")
    assert snapshot["both_sides"] is True
    assert snapshot["not_an_order"] is True
    assert len(snapshot["legs"]) == 2
