"""Factor profile contract tests: resolution, union, disjointness, severity."""

import pytest

from crypto_trader.factors.capture import EXPECTED_FACTOR_IDS
from crypto_trader.factors.health.states import FactorHealthState
from crypto_trader.factors.profiles import (
    BLOCKED,
    CANONICAL_PROFILE_NAMES,
    DEGRADED,
    READY,
    assess_profile,
    assess_profile_from_snapshot,
    resolve_profile,
)
from crypto_trader.factors.tool_gateway import FactorToolGateway

SYMBOL = "BTC-USDT-SWAP"
TIMEFRAME = "15m"


def candles(n=30):
    rows = []
    for i in range(n):
        c = 100 + i * 0.5
        rows.append(
            {
                "open": str(c - 0.2),
                "high": str(c + 0.3),
                "low": str(c - 0.4),
                "close": str(c),
                "volume": str(100 + i),
            }
        )
    return rows


# ----------------------------------------------------------------- resolution


def test_all_canonical_profiles_resolve():
    for name in CANONICAL_PROFILE_NAMES:
        profile = resolve_profile(name)
        assert profile.name == name
        assert profile.required_factors


def test_unknown_profile_rejected():
    with pytest.raises(ValueError):
        resolve_profile("ALPHA_BRAIN_V9")
    with pytest.raises(ValueError):
        resolve_profile("")  # empty must not silently match FULL


def test_required_and_optional_disjoint_for_every_canonical_profile():
    for name in CANONICAL_PROFILE_NAMES:
        profile = resolve_profile(name)
        overlap = set(profile.required_factors) & set(profile.optional_factors)
        assert not overlap, f"{name} overlaps: {overlap}"
        # construction-time validation also rejects duplicates
        from crypto_trader.factors.profiles import FactorProfile

        with pytest.raises(ValueError):
            FactorProfile(name="X", required_factors=("trend",), optional_factors=("trend",))


def test_full_union_behavior():
    full = resolve_profile("FULL")
    covered = set(full.required_factors) | set(full.optional_factors)
    # every computed factor is classified exactly once by FULL
    assert covered == set(EXPECTED_FACTOR_IDS)
    assert len(list(full.required_factors) + list(full.optional_factors)) == len(set(covered))
    for name in ("TREND", "MOMENTUM", "MEAN_REVERSION", "DERIVATIVES", "MICROSTRUCTURE"):
        for factor in resolve_profile(name).required_factors:
            assert factor in full.required_factors


# ------------------------------------------------------------------ semantics


def _statuses(**overrides):
    base = {factor: FactorHealthState.OK for factor in EXPECTED_FACTOR_IDS}
    base.update({k: v for k, v in overrides.items() if k != "__drop__"})
    return base


def test_ready_when_everything_usable():
    result = assess_profile(resolve_profile("TREND"), _statuses())
    assert result.readiness == READY
    assert result.blocked_by == () and result.degraded_by == ()


def test_valid_zero_counts_as_usable():
    statuses = _statuses(trend=FactorHealthState.VALID_ZERO)
    assert assess_profile(resolve_profile("TREND"), statuses).readiness == READY


def test_required_unhealthy_is_blocked():
    statuses = _statuses(trend=FactorHealthState.CALCULATION_FAILED)
    result = assess_profile(resolve_profile("TREND"), statuses)
    assert result.readiness == BLOCKED
    assert result.blocked_by == ("trend",)

    statuses_full = _statuses(funding_rate=FactorHealthState.DISABLED)
    assert assess_profile(resolve_profile("FULL"), statuses_full).readiness == BLOCKED


def test_optional_unhealthy_degrades_but_does_not_block():
    statuses = _statuses(breakout=FactorHealthState.MISSING_DATA)
    result = assess_profile(resolve_profile("TREND"), statuses)
    assert result.readiness == DEGRADED
    assert result.degraded_by == ("breakout",)
    assert result.blocked_by == ()


def test_blocked_outweighs_degraded_regardless_of_order():
    broken = {
        "trend": FactorHealthState.CALCULATION_FAILED,
        "breakout": FactorHealthState.MISSING_DATA,
    }
    import itertools

    readings = set()
    keys = list(broken)
    for order in itertools.permutations(keys):
        statuses = _statuses()
        for key in order:
            statuses[key] = broken[key]
        readings.add(assess_profile(resolve_profile("TREND"), statuses).readiness)
    assert readings == {BLOCKED}


def test_missing_status_entry_is_unusable_not_ignored():
    statuses = _statuses()
    del statuses["momentum"]
    result = assess_profile(resolve_profile("TREND"), statuses)
    assert result.readiness == BLOCKED
    assert "momentum" in result.missing_statuses


def test_unrecognized_status_string_is_unusable():
    statuses = _statuses(momentum="SOME_LLM_FREEFORM_STATE")
    assert assess_profile(resolve_profile("TREND"), statuses).readiness == BLOCKED


# ---------------------------------------------------- snapshot-path assessment


def test_assessment_from_real_snapshot_short_history_blocks_trend_profile():
    gateway = FactorToolGateway()
    snapshot = gateway.calculate_snapshot(symbol=SYMBOL, timeframe=TIMEFRAME, candles=candles(1))
    result = assess_profile_from_snapshot(snapshot, "TREND")
    assert result.readiness == BLOCKED
    assert "trend" in result.blocked_by


def test_assessment_from_healthy_snapshot_microstructure_with_book():
    gateway = FactorToolGateway()
    snapshot = gateway.calculate_snapshot(
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        candles=candles(),
        market_data={"bid_volume": "60", "ask_volume": "40"},
    )
    micro = assess_profile_from_snapshot(snapshot, "MICROSTRUCTURE")
    # buy_sell_imbalance shares the book-derived imbalance; cvd/aggr real zeros OK.
    assert micro.readiness in (READY, DEGRADED)


def test_no_book_microstructure_blocked_via_snapshot_path():
    gateway = FactorToolGateway()
    snapshot = gateway.calculate_snapshot(symbol=SYMBOL, timeframe=TIMEFRAME, candles=candles())
    result = assess_profile_from_snapshot(snapshot, "MICROSTRUCTURE")
    assert result.readiness == BLOCKED
    assert "orderbook_imbalance" in result.blocked_by
