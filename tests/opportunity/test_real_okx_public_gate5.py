"""Gate 5: real OKX public market-data qualification.

These tests hit the REAL public OKX endpoint. In a network-unavailable
environment they SKIP explicitly with a reason — they are never marked PASS.
No credentials are required or used; no order is ever placed.
"""

from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from crypto_trader.exchange.okx import OKXAdapter, OKXDiagnosticError
from crypto_trader.market_data.opportunity.board import OpportunityBoard
from crypto_trader.market_data.opportunity.factors import DEFAULT_FACTORS
from crypto_trader.market_data.opportunity.scanner import FactorScanner
from crypto_trader.market_data.opportunity.service import (
    OpportunityScannerService,
    ScannerConfig,
)
from crypto_trader.market_data.opportunity.universe import OkxUniverseManager
from crypto_trader.market_data.quality import build_candle_truth

PUBLIC_BASE = "https://www.okx.com"
TIMEOUT = 20.0


# ---------------------------------------------------------------------------
# Real-time snapshot consistency envelope (empirically calibrated)
# ---------------------------------------------------------------------------
# The broad and single open-interest calls are TWO INDEPENDENT live observations,
# not one immutable exchange snapshot, so exact float equality between them is
# not a valid real-time invariant: OKX open interest moves continuously.
#
# Calibration (100 paired live observations, 0 failures, 2026-09-14):
#   relative |single-broad|/broad : p50=0.0  p95=5.06e-05  p99=3.65e-04  max=3.65e-04
#   |single.ts - broad.ts| seconds: p50=0.488  p95=0.603  p99=0.785  max=0.806
#
# Envelope derived from the observed p99 (never guessed):
#   OI tolerance   T = max(0.0005, 3 x p99_drift) = max(0.0005, 0.0010952) = 0.0010952
#   Timestamp limit  = max(2.0, 3 x p99_delta)    = max(2.0, 2.3556)       = 2.3556 s
# Hard ceilings (a larger gap means a real endpoint/source mismatch, and the
# test MUST fail rather than widen the envelope):
#   T <= 0.005 (0.5 %)      TIMESTAMP_LIMIT <= 10.0 s
OI_RELATIVE_DRIFT_TOLERANCE = 0.0010952
OI_TIMESTAMP_DELTA_LIMIT_SECONDS = 2.3556
OI_RELATIVE_DRIFT_HARD_CEILING = 0.005
OI_TIMESTAMP_DELTA_HARD_CEILING = 10.0

# The envelope is only meaningful while it stays under the hard ceilings.  If a
# future calibration pushes past them the comparison must be investigated, not
# loosened further.
assert OI_RELATIVE_DRIFT_TOLERANCE <= OI_RELATIVE_DRIFT_HARD_CEILING
assert OI_TIMESTAMP_DELTA_LIMIT_SECONDS <= OI_TIMESTAMP_DELTA_HARD_CEILING


def _finite_positive(value) -> bool:
    """True only for a real, finite, strictly positive number."""
    import math

    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _finite_nonnegative(value) -> bool:
    import math

    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number >= 0


def _parse_okx_ts(value) -> float:
    """OKX millisecond epoch -> seconds.  Raises on anything unusable."""
    millis = int(value)
    assert millis > 0, f"provider timestamp must be positive, got {value}"
    return millis / 1000.0


def _network_available() -> bool:
    try:
        with socket.create_connection(("www.okx.com", 443), timeout=8):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _network_available(),
    reason="NETWORK_UNAVAILABLE: real OKX public endpoint unreachable (skipped, not passed)",
)


def _run(coro):
    """Run a live call, turning a transient transport failure into an explicit SKIP.

    An environment/network failure is never reported as PASS: it is skipped with
    the transport error in the reason (per the directive's honesty rule).
    """
    try:
        return asyncio.run(coro)
    except httpx.RequestError as exc:  # pragma: no cover - depends on the network
        pytest.skip(f"NETWORK_FLAKE: {type(exc).__name__} (environment failure, not a pass)")


def _client() -> OKXAdapter:
    return OKXAdapter(
        base_url=PUBLIC_BASE,
        api_key=None,
        api_secret=None,
        api_passphrase=None,
        demo=False,
    )


def test_real_okx_batch_funding_contract_returns_rows_not_empty():
    """Regression for the `instType`-only request that OKX rejects with 50014."""

    async def run():
        client = _client()
        try:
            rows = await client.get_funding_rates("SWAP")
        finally:
            await client.disconnect()
        return rows

    rows = _run(run())
    assert isinstance(rows, list)
    assert len(rows) > 100, f"batch funding returned only {len(rows)} rows"
    sample = rows[0]
    assert "instId" in sample
    assert "fundingRate" in sample
    # a factual zero must remain a real, present value
    zeros = [r for r in rows if float(r.get("fundingRate") or 0) == 0.0]
    assert zeros, "expected some factual zero funding rates in a real snapshot"


def test_real_okx_broad_open_interest_contract():
    """LIVE_OI_BATCH_SUPPORTED must be established by the real provider response.

    The correction directive requires this to be verified directly, not inferred
    from a failed ``instId=ANY`` call: open interest and funding have DIFFERENT
    contracts. ``instType=SWAP`` without ``instId`` is the broad form.
    """

    async def run():
        client = _client()
        try:
            rows = await client.get_open_interests("SWAP")
            single = await client.get_open_interest("BTC-USDT-SWAP")
        finally:
            await client.disconnect()
        return rows, single

    rows, single = _run(run())
    assert isinstance(rows, list)
    usdt = [row for row in rows if str(row.get("instId", "")).endswith("-USDT-SWAP")]
    live_batch_supported = len(usdt) > 100
    print(f"LIVE_OI_BATCH_SUPPORTED = {'YES' if live_batch_supported else 'NO'} "
          f"(rows={len(rows)}, usdt_rows={len(usdt)})")
    assert live_batch_supported, (
        f"OKX broad open interest returned only {len(usdt)} USDT perpetual rows"
    )
    sample = usdt[0]
    for field in ("instId", "oi", "oiCcy", "oiUsd", "ts"):
        assert field in sample, f"missing provider field: {field}"
    float(sample["oi"])
    float(sample["oiUsd"])
    assert int(sample["ts"]) > 0
    # --- Cross-endpoint consistency over two INDEPENDENT live observations ---
    # Same instrument, same canonical semantic fields, finite positive values,
    # fresh source timestamps, snapshots taken close together in time, and an
    # open-interest difference inside the calibrated real-time envelope.
    broad_btc = next(
        (row for row in usdt if row["instId"] == "BTC-USDT-SWAP"),
        None,
    )
    assert broad_btc is not None, "BTC-USDT-SWAP absent from the broad OI response"

    # Identity + canonical field presence on BOTH sides.
    assert broad_btc["instId"] == "BTC-USDT-SWAP"
    for field in ("oi", "oiCcy", "oiUsd", "ts"):
        assert field in broad_btc, f"broad row missing provider field: {field}"
    for field in (
        "open_interest",
        "open_interest_ccy",
        "open_interest_usd",
        "source_timestamp",
    ):
        assert field in single, f"single response missing canonical field: {field}"

    # Numeric validity on BOTH sides (NaN / inf / non-positive are failures).
    assert _finite_positive(broad_btc["oi"]), f"broad oi invalid: {broad_btc['oi']}"
    assert _finite_positive(single["open_interest"]), (
        f"single open_interest invalid: {single['open_interest']}"
    )
    assert _finite_nonnegative(broad_btc["oiCcy"]), (
        f"broad oiCcy invalid: {broad_btc['oiCcy']}"
    )
    assert _finite_nonnegative(single["open_interest_ccy"]), (
        f"single open_interest_ccy invalid: {single['open_interest_ccy']}"
    )
    assert _finite_nonnegative(broad_btc["oiUsd"]), (
        f"broad oiUsd invalid: {broad_btc['oiUsd']}"
    )
    assert _finite_nonnegative(single["open_interest_usd"]), (
        f"single open_interest_usd invalid: {single['open_interest_usd']}"
    )
    assert single["open_interest_usd"] is not None

    # Freshness on BOTH sides (timestamps parse and are positive).
    broad_ts = _parse_okx_ts(broad_btc["ts"])
    single_ts = _parse_okx_ts(single["source_timestamp"])

    # Snapshot proximity: the two observations must describe the same moment
    # closely enough that they are comparable at all.  No ordering is asserted
    # because these are two independent endpoints with no documented order.
    ts_delta = abs(single_ts - broad_ts)
    assert ts_delta <= OI_TIMESTAMP_DELTA_LIMIT_SECONDS, (
        f"broad/single open-interest snapshots are {ts_delta:.3f}s apart, beyond the "
        f"calibrated real-time window of {OI_TIMESTAMP_DELTA_LIMIT_SECONDS:.3f}s"
    )

    # Relative consistency inside the empirically calibrated envelope.  A gap
    # beyond the hard ceiling is a factual endpoint/source mismatch, not drift.
    broad_oi = float(broad_btc["oi"])
    single_oi = float(single["open_interest"])
    relative_drift = abs(single_oi - broad_oi) / broad_oi
    print(
        f"OI_CONSISTENCY relative_drift={relative_drift:.8f} "
        f"tolerance={OI_RELATIVE_DRIFT_TOLERANCE:.8f} "
        f"ts_delta={ts_delta:.3f}s limit={OI_TIMESTAMP_DELTA_LIMIT_SECONDS:.3f}s"
    )
    assert relative_drift <= OI_RELATIVE_DRIFT_TOLERANCE, (
        f"broad and single open interest differ by {relative_drift:.6%} "
        f"(broad={broad_oi}, single={single_oi}), beyond the calibrated "
        f"{OI_RELATIVE_DRIFT_TOLERANCE:.6%} real-time envelope; a difference this "
        "large indicates an endpoint/source mismatch rather than natural drift"
    )


def test_real_okx_insttype_only_funding_request_is_rejected():
    """Proves the OLD request shape could never return data (fail-closed)."""

    async def run():
        try:
            async with httpx.AsyncClient(base_url=PUBLIC_BASE, timeout=TIMEOUT) as raw:
                response = await raw.get(
                    "/api/v5/public/funding-rate", params={"instType": "SWAP"}
                )
            return response
        except httpx.RequestError as exc:  # pragma: no cover - network flake
            pytest.skip(f"NETWORK_FLAKE: {type(exc).__name__}")

    response = _run(run())
    assert response.status_code in (400, 200)
    body = response.json()
    assert str(body.get("code")) != "0"
    assert "instId" in str(body.get("msg", ""))


def test_real_okx_discovery_universe_is_usdt_perpetuals():
    async def run():
        client = _client()
        try:
            manager = OkxUniverseManager(client)
            snapshot = await manager.refresh()
        finally:
            await client.disconnect()
        return snapshot

    snapshot = _run(run())
    assert snapshot.size > 100
    for symbol, instrument in list(snapshot.instruments.items())[:50]:
        assert instrument.inst_id.endswith("-USDT-SWAP")
        assert instrument.state == "live"
        assert instrument.settle_ccy == "USDT"
        assert symbol.endswith("USDT")


def test_real_okx_scan_publishes_truthful_immutable_snapshot():
    """One real observation cycle: truthful counts + quality states."""

    async def run():
        client = _client()
        try:
            board = OpportunityBoard()
            service = OpportunityScannerService(
                universe=OkxUniverseManager(client),
                okx_client=client,
                board=board,
                scanner=FactorScanner(factors=DEFAULT_FACTORS),
                config=ScannerConfig(
                    candle_limit=40,
                    active_set_size=3,
                    rotation_size=3,
                    max_concurrency=4,
                    per_request_timeout_seconds=15.0,
                    whole_scan_deadline_seconds=90.0,
                ),
            )
            summary = await service.scan_once()
            return board, summary
        finally:
            await client.disconnect()

    board, summary = _run(run())
    snapshot = board.current_snapshot()
    assert snapshot is not None
    assert snapshot.scan_id == summary["scan_id"]
    assert snapshot.discovered_count > 100
    assert snapshot.observable_count > 100
    assert snapshot.observable_count <= snapshot.discovered_count
    assert 0 <= snapshot.analysis_success_count <= snapshot.analysis_attempted_count
    assert snapshot.analysis_attempted_count <= snapshot.discovered_count
    assert snapshot.execution_supported_count <= snapshot.observable_count
    assert snapshot.status in ("COMPLETE", "PARTIAL")
    assert snapshot.is_expired() is False
    funding_batch = snapshot.data_quality_summary["batch"]["funding"]
    assert funding_batch == "VALID", snapshot.data_quality_summary["batch"]
    # real funding facts are present with a real quality state
    funding_states = {
        row["funding_quality"] for row in snapshot.observable_rows
    }
    assert "VALID" in funding_states
    # turnover is labelled as an estimate everywhere
    assert "estimated_quote_turnover_24h" in snapshot.data_quality_summary["turnover_semantics"]


def test_real_okx_candles_are_closed_and_contiguous_enough():
    async def run():
        client = _client()
        try:
            rows = await client.get_candles("BTC-USDT-SWAP", "1m", 20)
        finally:
            await client.disconnect()
        return rows

    rows = _run(run())
    assert len(rows) >= 5
    # OKX returns the in-progress candle too; only CLOSED candles may feed
    # history, and the truth contract must report the difference.
    assert any(str(row[8]) == "0" for row in rows), "expected an in-progress candle"
    closed, truth = build_candle_truth(
        requested_count=20,
        rows=rows,
        bar_seconds=60.0,
        now=datetime.now(UTC),
    )
    assert truth.unique_closed_count >= 5
    assert truth.unique_closed_count == len(closed)
    assert truth.quality in ("VALID", "PARTIAL")
    timestamps = [ts for ts, _ in closed]
    gaps = [
        (later - earlier) / 1000.0
        for earlier, later in zip(timestamps, timestamps[1:], strict=False)
        if (later - earlier) / 1000.0 > 90
    ]
    assert not gaps, f"unexpected candle gaps in a 20-bar 1m request: {gaps}"
    latest = datetime.fromtimestamp(timestamps[-1] / 1000, tz=UTC)
    assert latest <= datetime.now(UTC) + timedelta(seconds=10)


def test_real_okx_funding_failure_semantics_are_truthful():
    """A rejected instrument must raise, never silently become zero funding."""

    async def run():
        client = _client()
        try:
            try:
                await client.get_funding_rate_fallback("NOTAREAL-USDT-SWAP")
            except OKXDiagnosticError as exc:
                return exc
        finally:
            await client.disconnect()
        return None

    error = _run(run())
    assert error is not None
