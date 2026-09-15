"""Phase 6: identity lineage builder/validator."""

from __future__ import annotations

from crypto_trader.runtime.lineage import (
    LINEAGE_STAGES,
    build_lineage,
    validate_lineage,
)


def _full_values() -> dict:
    return {
        "opportunity_id": "opp-1",
        "decision_id": "dec-1",
        "position_episode_id": "ep-1",
        "leg_id": "leg-1",
        "trade_plan_version": 2,
        "intent_id": "int-1",
        "execution_id": "exec-1",
        "client_order_id": "coid-1",
        "exchange_order_id": "ex-1",
        "fill_ids": ["fill-1", "fill-2"],
    }


def test_complete_lineage_covers_all_stages() -> None:
    chain = build_lineage(**_full_values())
    result = validate_lineage(chain)
    assert result["complete"] is True
    assert result["trade_complete"] is True
    assert result["missing"] == []
    assert result["stages"] == list(LINEAGE_STAGES)
    assert result["authority"] == "LINEAGE_ONLY"
    assert result["is_order"] is False


def test_missing_fill_and_exchange_ids_are_reported() -> None:
    values = _full_values()
    values["fill_ids"] = []
    values["exchange_order_id"] = None
    chain = build_lineage(**values)
    result = validate_lineage(chain)
    assert result["complete"] is False
    assert result["trade_complete"] is False
    assert set(result["missing"]) == {"exchange_order_id", "fill_ids"}


def test_decision_without_opportunity_is_trade_complete_if_trade_links_exist() -> None:
    values = _full_values()
    values.pop("opportunity_id")
    values.pop("position_episode_id")
    values.pop("leg_id")
    result = validate_lineage(build_lineage(**values))
    assert result["complete"] is False
    assert result["trade_complete"] is True
    assert set(result["missing"]) == {"opportunity_id", "position_episode_id", "leg_id"}


def test_unexpected_keys_are_surfaced_without_breaking_the_chain() -> None:
    values = _full_values()
    values["rogue_field"] = "x"
    result = validate_lineage(build_lineage(**values))
    assert result["unexpected"] == ["rogue_field"]
    assert result["trade_complete"] is True
