"""Phase 5: assembled Growth daily report."""

from __future__ import annotations

from crypto_trader.learning.growth_report import build_growth_daily_report
from crypto_trader.market_data.opportunity.daily_freeze import DailyOpportunityFreezer
from crypto_trader.market_data.opportunity.outcomes import (
    OpportunityOutcomeRecorder,
    evaluate_opportunity,
)


async def test_growth_daily_report_assembles_all_sections(database) -> None:
    freezer = DailyOpportunityFreezer(database.session_factory)
    recorder = OpportunityOutcomeRecorder(database.session_factory)

    await freezer.freeze(
        "2026-09-16",
        [
            {"symbol": "BTCUSDT", "score": 90.0, "candidate_source": "market_observer"},
            {"symbol": "ETHUSDT", "score": 80.0, "candidate_source": "market_observer"},
        ],
    )
    await recorder.record(
        trading_day="2026-09-16",
        symbol="BTCUSDT",
        outcomes=evaluate_opportunity(
            frozen_price=100.0,
            expected_direction="LONG",
            traded=True,
            window_prices={"1h": 101.0},
        ),
    )
    events = [
        {"kind": "ADD", "outcome_bps": 5.0},
        {"kind": "HEDGE", "outcome_bps": -2.0},
        {"kind": "MODIFY_EXIT"},
        {"kind": "FAST_PROFIT_PROTECTION", "outcome_bps": 8.0},
        {"kind": "REENTRY", "outcome_bps": 1.0},
        {"kind": "RISK_L1"},
        {"kind": "LLM_INVOCATION", "outcome_bps": 3.0},
    ]
    verdicts = [
        {"verdict": "POSSIBLE_THESIS_RATIONALIZATION", "flags": ["BASE_EXIT_MOVED_FARTHER"]},
        {"verdict": "DISCIPLINE_OK", "flags": []},
    ]

    report = await build_growth_daily_report(
        trading_day="2026-09-16",
        freezer=freezer,
        outcome_recorder=recorder,
        events=events,
        rationalization_verdicts=verdicts,
    )

    assert report["trading_day"] == "2026-09-16"
    assert report["top10_count"] == 2
    assert [entry["symbol"] for entry in report["top10"]] == ["BTCUSDT", "ETHUSDT"]
    assert report["outcomes"]["rows"] == 1
    assert report["outcomes"]["labels"]["TRADED_CORRECT"] == 1
    assert report["reviews"]["complete"] is True
    assert report["rationalization"]["checks"] == 2
    assert report["rationalization"]["flagged"] == 1
    assert report["authority"] == "LEARNING_ONLY"
    assert report["is_order"] is False
    assert report["can_modify_core"] is False
