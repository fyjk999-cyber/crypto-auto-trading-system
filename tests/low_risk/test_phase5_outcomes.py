"""Phase 5 Growth V2: outcome taxonomy + MFE/MAE evaluation."""

from __future__ import annotations

from crypto_trader.market_data.opportunity.outcomes import (
    classify_outcome,
    evaluate_opportunity,
)


def test_taxonomy_2x2() -> None:
    assert (
        classify_outcome(expected_direction="LONG", traded=True, net_return_bps=5)
        == "TRADED_CORRECT"
    )
    assert (
        classify_outcome(expected_direction="LONG", traded=True, net_return_bps=-5)
        == "TRADED_WRONG"
    )
    assert (
        classify_outcome(expected_direction="LONG", traded=False, net_return_bps=-5)
        == "NOT_TRADED_CORRECTLY_AVOIDED"
    )
    assert (
        classify_outcome(expected_direction="LONG", traded=False, net_return_bps=5)
        == "NOT_TRADED_MISSED"
    )


def test_long_and_short_returns_are_mirrored() -> None:
    long_out = evaluate_opportunity(
        frozen_price=100.0,
        expected_direction="LONG",
        traded=True,
        window_prices={"1h": 101.0},
    )[0]
    short_out = evaluate_opportunity(
        frozen_price=100.0,
        expected_direction="SHORT",
        traded=True,
        window_prices={"1h": 101.0},
    )[0]
    assert long_out.return_bps == 100.0
    assert short_out.return_bps == -100.0
    assert long_out.label == "TRADED_CORRECT"
    assert short_out.label == "TRADED_WRONG"


def test_costs_can_flip_correctness() -> None:
    outcome = evaluate_opportunity(
        frozen_price=100.0,
        expected_direction="LONG",
        traded=True,
        window_prices={"15m": 100.05},
        all_in_cost_bps=8.0,
    )[0]
    assert outcome.return_bps == 5.0
    assert outcome.net_return_bps == -3.0
    assert outcome.label == "TRADED_WRONG"


def test_mfe_mae_from_path_and_horizon_filtering() -> None:
    outcomes = evaluate_opportunity(
        frozen_price=100.0,
        expected_direction="LONG",
        traded=False,
        window_prices={"30m": 101.5, "4h": 99.0},
        path_prices=[100.2, 102.0, 100.5, 98.5],
    )
    assert [outcome.horizon for outcome in outcomes] == ["30m", "4h"]
    assert outcomes[0].mfe_bps == 200.0  # 102.0
    assert outcomes[0].mae_bps == -150.0  # 98.5
    assert outcomes[0].net_return_bps == 150.0
    assert outcomes[0].label == "NOT_TRADED_MISSED"
    assert outcomes[0].authority == "LEARNING_ONLY"
    assert outcomes[0].is_order is False
