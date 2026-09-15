"""Phase 5 Growth V2: daily TOP-10 freeze without hindsight."""

from __future__ import annotations

from crypto_trader.market_data.opportunity.daily_freeze import DailyOpportunityFreezer


def _candidate(symbol: str, score: float) -> dict:
    return {
        "symbol": symbol,
        "score": score,
        "candidate_source": "market_observer",
        "factor_evidence": [{"factor": "momentum"}],
    }


async def test_daily_top10_freezes_decision_time_ranking(database) -> None:
    freezer = DailyOpportunityFreezer(database.session_factory)
    candidates = [_candidate(f"SYM{i}", 100.0 - i) for i in range(15)]

    result = await freezer.freeze("2026-09-16", candidates)
    assert result["frozen"] is True
    assert result["already_frozen"] is False
    assert result["authority"] == "LEARNING_ONLY"
    assert result["not_an_order"] is True
    entries = result["entries"]
    assert len(entries) == 10
    assert [entry["rank"] for entry in entries] == list(range(1, 11))
    assert [entry["symbol"] for entry in entries][:3] == ["SYM0", "SYM1", "SYM2"]
    assert entries[0]["score"] == 100.0
    assert entries[0]["factor_evidence"] == [{"factor": "momentum"}]


async def test_frozen_top10_is_immutable_no_hindsight(database) -> None:
    freezer = DailyOpportunityFreezer(database.session_factory)
    await freezer.freeze("2026-09-16", [_candidate("AAA", 1.0), _candidate("BBB", 2.0)])

    # Later (outcome-informed) scores must NOT rewrite the frozen day.
    again = await freezer.freeze(
        "2026-09-16", [_candidate("BBB", 99.0), _candidate("AAA", 98.0)]
    )
    assert again["already_frozen"] is True
    assert [entry["symbol"] for entry in again["entries"]] == ["BBB", "AAA"]
    assert [entry["score"] for entry in again["entries"]] == [2.0, 1.0]

    stored = await freezer.get("2026-09-16")
    assert [entry["symbol"] for entry in stored] == ["BBB", "AAA"]
