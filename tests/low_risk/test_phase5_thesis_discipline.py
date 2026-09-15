"""Phase 5: POSSIBLE_THESIS_RATIONALIZATION detection."""

from __future__ import annotations

from crypto_trader.learning.thesis_discipline import check_thesis_rationalization

ORIGINAL = "breakout continuation over 105 with trend support"


def test_clean_hold_on_losing_position_is_not_flagged() -> None:
    result = check_thesis_rationalization(
        direction="LONG",
        entry_price=100.0,
        current_price=98.0,
        original_thesis=ORIGINAL,
        new_thesis=ORIGINAL,
        original_base_exit=105.0,
        new_base_exit=105.0,
    )
    assert result.verdict == "DISCIPLINE_OK"
    assert result.flags == []
    assert result.is_order is False


def test_lowered_base_exit_with_original_thesis_is_rationalization() -> None:
    result = check_thesis_rationalization(
        direction="LONG",
        entry_price=100.0,
        current_price=97.0,
        original_thesis=ORIGINAL,
        new_thesis=ORIGINAL,  # unchanged thesis, target quietly moved
        original_base_exit=105.0,
        new_base_exit=95.0,
    )
    assert result.verdict == "POSSIBLE_THESIS_RATIONALIZATION"
    assert "BASE_EXIT_MOVED_FARTHER_FROM_ENTRY" in result.flags
    assert "THESIS_UNCHANGED_AFTER_LOSS" in result.flags


def test_revised_thesis_with_new_justification_is_allowed() -> None:
    result = check_thesis_rationalization(
        direction="LONG",
        entry_price=100.0,
        current_price=97.0,
        original_thesis=ORIGINAL,
        new_thesis="regime change: new evidence shows range, independent thesis at 96",
        original_base_exit=105.0,
        new_base_exit=96.0,
    )
    assert result.verdict == "THESIS_REVISED_WITH_NEW_JUSTIFICATION"
    assert result.license_to_modify is True
    assert "BASE_EXIT_MOVED_FARTHER_FROM_ENTRY" in result.flags


def test_profit_target_roll_is_not_rationalization() -> None:
    result = check_thesis_rationalization(
        direction="LONG",
        entry_price=100.0,
        current_price=106.0,
        original_thesis=ORIGINAL,
        new_thesis=ORIGINAL,
        original_base_exit=105.0,
        new_base_exit=110.0,  # trailing higher while profitable
    )
    assert result.verdict == "DISCIPLINE_OK"


def test_weakened_invalidation_is_flagged_for_shorts_too() -> None:
    result = check_thesis_rationalization(
        direction="SHORT",
        entry_price=100.0,
        current_price=103.0,
        original_thesis="downtrend continuation below 95",
        new_thesis="downtrend continuation below 95",
        original_base_exit=95.0,
        new_base_exit=105.0,
        original_invalidation=105.0,
        new_invalidation=110.0,
    )
    assert result.verdict == "POSSIBLE_THESIS_RATIONALIZATION"
    assert "INVALIDATION_WEAKENED" in result.flags
    assert result.authority == "LEARNING_ONLY"
