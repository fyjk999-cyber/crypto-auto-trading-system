"""Phase C: extended factual labels (no LLM opinion labels)."""

from __future__ import annotations

from crypto_trader.market_data.opportunity.outcomes import (
    HORIZONS,
    OpportunityOutcomeRecorder,
    evaluate_opportunity,
)


def test_horizons_include_1m_and_5m() -> None:
    assert "1m" in HORIZONS and "5m" in HORIZONS
    outcomes = evaluate_opportunity(
        frozen_price=100.0,
        expected_direction="LONG",
        traded=False,
        window_prices={"1m": 100.05, "5m": 99.95},
    )
    assert [o.horizon for o in outcomes] == ["1m", "5m"]


def test_net_edge_threshold_not_price_up_labelling() -> None:
    # Spec example: gross +0.18% (18bps) vs all-in cost 0.22% (22bps) -> NOT profitable.
    outcome = evaluate_opportunity(
        frozen_price=100.0,
        expected_direction="LONG",
        traded=False,
        window_prices={"5m": 100.18},
        all_in_cost_bps=22.0,
    )[0]
    assert round(outcome.long_gross_bps, 6) == 18.0
    assert round(outcome.long_net_bps, 6) == -4.0
    assert round(outcome.net_edge_bps, 6) == -4.0
    assert outcome.net_edge_label == "NOT_PROFITABLE"

    profitable = evaluate_opportunity(
        frozen_price=100.0,
        expected_direction="LONG",
        traded=False,
        window_prices={"5m": 100.50},
        all_in_cost_bps=10.0,
        min_edge_bps=20.0,
    )[0]
    assert profitable.long_net_bps == 40.0
    assert profitable.net_edge_label == "PROFITABLE"


def test_path_high_low_realized_vol_and_direction_split() -> None:
    outcome = evaluate_opportunity(
        frozen_price=100.0,
        expected_direction="SHORT",
        traded=False,
        window_prices={"15m": 100.5},
        path_prices=[100.0, 101.0, 99.0, 100.5],
        all_in_cost_bps=5.0,
    )[0]
    assert outcome.future_high == 101.0
    assert outcome.future_low == 99.0
    assert outcome.realized_volatility > 0
    assert round(outcome.long_gross_bps, 6) == 50.0
    assert round(outcome.short_gross_bps, 6) == -50.0
    assert round(outcome.short_net_bps, 6) == -55.0
    assert outcome.expected_direction == "SHORT"
    assert "CALCULATION" not in outcome.label


async def test_recorder_persists_extended_labels(database) -> None:
    recorder = OpportunityOutcomeRecorder(database.session_factory)
    outcomes = evaluate_opportunity(
        frozen_price=100.0,
        expected_direction="LONG",
        traded=True,
        window_prices={"1m": 100.18},
        all_in_cost_bps=22.0,
    )
    assert await recorder.record(trading_day="2026-09-16", symbol="MLTEST", outcomes=outcomes) == 1
    rows = await recorder.list_for_day("2026-09-16")
    assert rows[0]["label"] == "TRADED_WRONG"  # net is negative after costs
    assert rows[0]["net_edge_label"] == "NOT_PROFITABLE"
