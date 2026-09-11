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
    # single-instrument retrieval stays consistent with the broad row
    broad_btc = next(row for row in usdt if row["instId"] == "BTC-USDT-SWAP")
    assert float(single["open_interest"]) == float(broad_btc["oi"])
    assert single["open_interest_usd"] is not None


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
