"""Factor health integration with the canonical snapshot path.

Covers: healthy factor, real zero vs failure distinction, legacy confidence=0
and NO_BOOK mapping, missing candles, insufficient history, calculator failure
isolation, persistence of failed/status fields into FactorSnapshotContract,
unchanged factor math and deterministic output.
"""

import json
from decimal import Decimal

from crypto_trader.factors.capture import FactorCaptureEngine
from crypto_trader.factors.health import (
    FactorHealthAssessment,
    FactorHealthState,
    report_from_legacy_result,
)
from crypto_trader.factors.models import FactorResult
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


def _legacy(factor_name="trend", value="1", confidence="0.9", metadata=None):
    return FactorResult(
        factor_name=factor_name,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        value=Decimal(value),
        confidence=Decimal(confidence),
        metadata=metadata or {},
    )


# ---------------------------------------------------------------- health states


def test_healthy_factor_maps_ok():
    assessment = report_from_legacy_result(_legacy())
    assert assessment.state == FactorHealthState.OK


def test_real_numerical_zero_is_valid_zero():
    assessment = report_from_legacy_result(_legacy(factor_name="cvd", value="0", confidence="0.4"))
    assert assessment.state == FactorHealthState.VALID_ZERO
    assert assessment.is_usable()


def test_legacy_confidence_zero_maps_missing_data_not_valid_zero():
    assessment = report_from_legacy_result(
        _legacy(factor_name="orderbook_imbalance", value="0", confidence="0")
    )
    assert assessment.state == FactorHealthState.MISSING_DATA
    assert not assessment.is_usable()


def test_no_book_metadata_maps_missing_data_with_detail():
    assessment = report_from_legacy_result(
        _legacy(
            factor_name="orderbook_imbalance",
            value="0",
            confidence="0",
            metadata={"status": "NO_BOOK"},
        )
    )
    assert assessment.state == FactorHealthState.MISSING_DATA
    assert "NO_BOOK" in assessment.detail


def test_no_trades_metadata_maps_missing_data():
    assessment = report_from_legacy_result(
        _legacy(
            factor_name="buy_sell_imbalance",
            value="0",
            confidence="0",
            metadata={"status": "NO_TRADES"},
        )
    )
    assert assessment.state == FactorHealthState.MISSING_DATA


def test_null_value_never_becomes_fake_zero():
    result = _legacy(factor_name="trend", value="0", confidence="0.8")
    object.__setattr__(result, "value", None)
    assessment = report_from_legacy_result(result)
    assert assessment.state == FactorHealthState.CALCULATION_FAILED
    assert assessment.detail == "NULL_VALUE"


def test_assessment_rejects_unknown_state():
    try:
        FactorHealthAssessment(factor_name="trend", state="SOMETHING_ELSE")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown health state must be rejected")


# ------------------------------------------------------- canonical path status


def test_gateway_healthy_run_all_ok_statuses():
    snapshot = FactorToolGateway().calculate_snapshot(
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        candles=candles(),
        market_data={"bid_volume": "60", "ask_volume": "40", "cvd": "12"},
    )
    # Healthy run allows OK and structurally-real zero values only.
    statuses = {e.status for e in snapshot.factors}
    assert statuses <= {"OK", "VALID_ZERO"}
    assert statuses
    assert snapshot.failed_factors == ()
    assert snapshot.calculation_warnings == ()


def test_gateway_real_zero_persists_as_valid_zero_entry():
    # cvd is absent from market_data -> real numerical zero with confidence 0.4.
    snapshot = FactorToolGateway().calculate_snapshot(
        symbol=SYMBOL, timeframe=TIMEFRAME, candles=candles()
    )
    cvd = snapshot.factor("cvd")
    assert cvd is not None
    assert cvd.raw_value == "0"
    assert cvd.status == FactorHealthState.VALID_ZERO
    assert cvd.factor_name not in snapshot.failed_factors


def test_no_book_factor_is_failed_without_fake_zero_entry():
    snapshot = FactorToolGateway().calculate_snapshot(
        symbol=SYMBOL, timeframe=TIMEFRAME, candles=candles()
    )
    assert snapshot.factor("orderbook_imbalance") is None
    assert "orderbook_imbalance" in snapshot.failed_factors
    joined = "\n".join(snapshot.calculation_warnings)
    assert "orderbook_imbalance:MISSING_DATA:NO_BOOK" in joined


def test_missing_candles_explicit_failure_and_warning():
    snapshot = FactorToolGateway().calculate_snapshot(
        symbol=SYMBOL, timeframe=TIMEFRAME, candles=[]
    )
    assert snapshot.factors == ()
    assert snapshot.failed_factors
    assert "INSUFFICIENT_HISTORY" in snapshot.calculation_warnings


def test_short_history_marks_unproduced_factors_insufficient_history():
    snapshot = FactorToolGateway().calculate_snapshot(
        symbol=SYMBOL, timeframe=TIMEFRAME, candles=candles(1)
    )
    # Price/volume/volatility need >= 2 candles; orderflow/derivatives still compute.
    for factor_id in ("return", "momentum", "trend", "atr", "volume_change"):
        assert factor_id in snapshot.failed_factors
        assert f"{factor_id}:INSUFFICIENT_HISTORY" in snapshot.calculation_warnings
    assert snapshot.factor("funding_rate") is not None


def test_calculator_failure_isolated_per_group_and_reported():
    gateway = FactorToolGateway()

    def _boom(*args, **kwargs):
        raise RuntimeError("derivatives feed exploded")

    gateway.capture_engine._capture_derivatives = _boom
    snapshot = gateway.calculate_snapshot(symbol=SYMBOL, timeframe=TIMEFRAME, candles=candles())
    # Other groups still produce usable values.
    assert snapshot.factor("trend") is not None
    assert snapshot.factor("trend").status == FactorHealthState.OK
    # Failed group recorded explicitly with cause, never faked to zero.
    for factor_id in ("funding_rate", "open_interest", "liquidation_pressure"):
        assert factor_id in snapshot.failed_factors
        warning = next(w for w in snapshot.calculation_warnings if w.startswith(f"{factor_id}:"))
        assert "CALCULATION_FAILED" in warning
        assert "RuntimeError" in warning
    for factor_id in ("funding_rate", "open_interest"):
        assert snapshot.factor(factor_id) is None


def test_capture_engine_records_error_map_directly():
    engine = FactorCaptureEngine()

    def _boom(*args, **kwargs):
        raise ValueError("bad candle")

    engine._capture_volatility = _boom
    results = engine.capture(SYMBOL, TIMEFRAME, candles(), None)
    names = {r.factor_name for r in results}
    assert "trend" in names
    assert set(engine.last_calculation_errors) == {
        "atr",
        "realized_volatility",
        "volatility_regime",
    }


def test_status_and_failures_serialized_in_snapshot_dict():
    snapshot = FactorToolGateway().calculate_snapshot(
        symbol=SYMBOL, timeframe=TIMEFRAME, candles=candles(1)
    )
    payload = json.loads(json.dumps(snapshot.to_dict()))
    # Orderflow/derivatives produce real zero-valued entries on one candle.
    assert any(entry["status"] == FactorHealthState.VALID_ZERO for entry in payload["factors"])
    assert "return" in payload["failed_factors"]
    assert any(w.startswith("return:INSUFFICIENT_HISTORY") for w in payload["calculation_warnings"])


# --------------------------------------------------------- math and determinism


def test_existing_factor_math_unchanged():
    snapshot = FactorToolGateway().calculate_snapshot(
        symbol=SYMBOL, timeframe=TIMEFRAME, candles=candles()[:2]
    )
    # Two candles closes 100 -> 100.5: ret = 0.005, scaled by 100 => 0.500.
    entry = snapshot.factor("return")
    assert entry.raw_value == str(Decimal("0.500"))
    assert entry.confidence == str(Decimal("0.9"))


def test_deterministic_output_for_identical_inputs():
    gateway_inputs = dict(
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        candles=candles(),
        market_data={"bid_volume": "60", "ask_volume": "40"},
    )
    a = FactorToolGateway().calculate_snapshot(**gateway_inputs)
    b = FactorToolGateway().calculate_snapshot(**gateway_inputs)

    def strip_ids(s):
        return [
            (e.factor_name, e.raw_value, e.confidence, e.status, e.contribution) for e in s.factors
        ]

    assert strip_ids(a) == strip_ids(b)
    assert (a.failed_factors, a.calculation_warnings) == (b.failed_factors, b.calculation_warnings)
