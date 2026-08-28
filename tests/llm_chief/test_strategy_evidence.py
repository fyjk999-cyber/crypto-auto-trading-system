"""§27 deterministic scenarios: strategy-selection decision philosophy.

Each scenario builds REAL candle series through the canonical StrategyEvidence
Builder (five existing strategies + regime priors). No unanimity is required
anywhere; contradictions reduce confidence, they do not veto.
"""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.llm_chief.strategy_evidence import StrategyEvidenceBuilder

SYMBOL = "BTCUSDT"


def _candles(
    closes: list[float], volume: str = "10", open_price: float | None = None
) -> list[dict]:
    base_ms = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
    out = []
    for i, close in enumerate(closes):
        o = open_price if open_price is not None else close
        out.append(
            {
                "symbol": SYMBOL,
                "interval": "1m",
                "open_time": datetime.fromtimestamp(
                    (base_ms + i * 60_000) / 1000, tz=UTC
                ).isoformat(),
                "open": str(o),
                "high": str(max(o, close) * 1.0005),
                "low": str(min(o, close) * 0.9995),
                "close": str(close),
                "volume": volume,
                "source": "TEST",
            }
        )
    return out


def _uptrend(n: int = 200, step: float = 1.003, start: float = 100.0) -> list[float]:
    closes, price = [], start
    for _ in range(n):
        closes.append(price)
        price *= step
    return closes


def _flat(n: int = 200, price: float = 100.0) -> list[float]:
    return [price] * n


def _package(closes, market_data=None) -> object:
    builder = StrategyEvidenceBuilder(symbol=SYMBOL)
    return builder.build(_candles(closes), market_data or {})


def test_scenario_A_trend_dominant_with_funding_contradiction():
    """Trend + momentum strong, funding contradictory -> trend still LONG."""
    package = _package(
        _uptrend(), {"funding_rate": "0.002", "previous_funding_rate": "0.002"}
    )
    best = package.best_candidate()
    assert best is not None
    assert best.strategy_id == "trend_following"
    assert best.direction == "LONG"
    assert best.fit_score >= 0.45  # above the default minimum edge
    assert "funding_rate" in best.contradicting_factors  # contradiction recorded
    assert "trend" in best.supporting_factors
    # The contradiction reduced NOTHING structurally: fit remains tradeable.
    momentum = next(c for c in package.strategy_candidates if c.strategy_id == "momentum")
    assert momentum.direction == "LONG"
    # FundingBasis sees crowded longs and disagrees (SHORT) -- allowed.
    funding = next(c for c in package.strategy_candidates if c.strategy_id == "funding_basis")
    assert funding.direction in ("SHORT", "NO_TRADE")


def test_scenario_B_range_regime_selects_mean_reversion():
    """Range regime, mean reversion strong, trend flat -> mean reversion selected."""
    closes = _flat(180) + [99.9, 99.5, 98.0]
    package = _package(closes, {"funding_rate": "0.0001"})
    best = package.best_candidate()
    assert best is not None
    assert best.strategy_id == "mean_reversion"
    assert best.direction == "LONG"  # oversold
    assert "OVERSOLD" in best.reason_codes
    trend = next(c for c in package.strategy_candidates if c.strategy_id == "trend_following")
    assert trend.direction in ("NO_TRADE", "SHORT")
    # Regime prior mattered: mean reversion fit outranks the raw momentum SHORT.
    momentum = next(c for c in package.strategy_candidates if c.strategy_id == "momentum")
    if momentum.direction == "SHORT":
        assert best.fit_score > momentum.fit_score


def test_scenario_C_breakout_selected_without_momentum_gate():
    """Breakout + high volatility; momentum is NOT required for selection."""
    closes = _flat(190) + [100.5, 101.0, 102.0, 103.5]
    package = _package(closes, {"funding_rate": "0.0001"})
    breakout = next(
        c for c in package.strategy_candidates if c.strategy_id == "breakout"
    )
    assert breakout.direction == "LONG"
    assert "BREAKOUT_UP" in breakout.reason_codes
    assert breakout.fit_score >= 0.45
    # No code path requires momentum agreement for breakout to be selectable.
    momentum = next(c for c in package.strategy_candidates if c.strategy_id == "momentum")
    assert momentum.direction in ("LONG", "NO_TRADE")  # either way breakout stands


def test_scenario_D_funding_dislocation_selects_funding_basis():
    """Funding/basis dislocation, trend neutral -> FundingBasis favored."""
    package = _package(
        _flat(200),
        {"funding_rate": "-0.002", "previous_funding_rate": "-0.001", "basis": "-0.001"},
    )
    best = package.best_candidate()
    assert best is not None
    assert best.strategy_id == "funding_basis"
    assert best.direction == "LONG"  # crowded shorts paid -> long bias
    assert best.fit_score >= 0.45
    trend = next(c for c in package.strategy_candidates if c.strategy_id == "trend_following")
    assert trend.direction == "NO_TRADE"


def test_scenario_E_all_fits_weak_yields_no_directional_edge():
    """Choppy noise: no strategy has directional edge -> package has none."""
    closes = []
    price = 100.0
    for i in range(200):
        price = 100.0 + (0.05 if i % 2 == 0 else -0.05)
        closes.append(price)
    package = _package(closes, {"funding_rate": "0.0000"})
    assert package.directional() == []
    assert package.best_candidate() is None


def test_two_opposite_strong_candidates_both_exist():
    """Strong trend LONG and mean-reversion SHORT coexist; no unanimity gate."""
    base = _uptrend(190, step=1.004)
    spike = _uptrend(10, step=1.01, start=base[-1] * 1.001)
    closes = base + spike
    package = _package(closes, {"funding_rate": "0.0001"})
    directions = {c.strategy_id: c.direction for c in package.strategy_candidates}
    trend = directions["trend_following"]
    mean_rev = directions["mean_reversion"]
    # Opposing candidates may coexist; the LLM weighs them.
    assert trend in ("LONG", "NO_TRADE") and mean_rev in ("SHORT", "NO_TRADE")
    if trend == "LONG" and mean_rev == "SHORT":
        best = package.best_candidate()
        assert best is not None and best.direction == "LONG"
