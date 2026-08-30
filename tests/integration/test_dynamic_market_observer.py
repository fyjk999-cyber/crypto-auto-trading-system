"""Phase C/D acceptance: dynamic all-market observer wiring.

Directive coverage:
LAYER1_BATCH_SCAN     : one batch request per product class (no per-symbol REST)
AI_ATTENTION          : non-core rotation owned by the Market Observer AI over
                        a compressed all-market digest; NO volume Top-K, NO
                        rank fallback (P1 CS-20260830-034530-P3-AI-ATTENTION)
STALE_MARKING         : failed refresh degrades freshness to STALE, never
                        fabricates, never blocks
WS_BOUND_AND_FALLBACK : ws candidate set bounded <=50, mode FALLBACK when WS
                        is down
ADVISORY_ONLY         : observer failure leaves decision context absent,
                        trading continues (fail-open)
DYNAMIC_ROTATION      : multi adapter rotation = core (always retained) +
                        bounded AI-attended dynamic candidates
SNAPSHOT_VISIBLE      : engine runtime_snapshot exposes market_observer
"""

import time
from datetime import UTC, datetime

from crypto_trader.market_data.observer import (
    HierarchicalMarketObserver,
    OKXTickerWsManager,
)
from crypto_trader.market_data.universe import MarketSnapshotBatch
from crypto_trader.runtime.multi_symbol_chief_trader import (
    MultiSymbolChiefTraderStrategyAdapter,
)


class FakeDataClient:
    def __init__(self):
        self.calls: list[str] = []
        self.fail = False

    async def get_tickers(self, inst_type: str, uly=None):
        self.calls.append(inst_type)
        if self.fail:
            raise RuntimeError("network down")
        if inst_type == "SPOT":
            return [
                {"instId": "BTC-USDT", "last": "60000", "bidPx": "59999",
                 "askPx": "60001", "volCcy24h": "1000", "vol24h": "10",
                 "ts": "1"},
                {"instId": "TRX-USDT", "last": "0.26", "bidPx": "0.2599",
                 "askPx": "0.2601", "volCcy24h": "500000", "vol24h": "100",
                 "ts": "2"},
            ]
        return [
            {"instId": "BTC-USDT-SWAP", "last": "60010", "bidPx": "60009",
             "askPx": "60011", "volCcy24h": "5000", "vol24h": "80", "ts": "3"},
            {"instId": "DOGE-USDT-SWAP", "last": "0.08", "bidPx": "0.0799",
             "askPx": "0.0801", "volCcy24h": "2000000", "vol24h": "900",
             "ts": "4"},
        ]


def _observer(client, clock=time.monotonic):
    return HierarchicalMarketObserver(
        _Universe(client),
        ws_manager=None,
        scan_interval_seconds=60.0,
        clock=clock,
    )


class _Universe:
    def __init__(self, client):
        self.data_client = client

    async def layer1_batch(self, inst_type):

        batch = MarketSnapshotBatch(
            batch_id=f"l1-{inst_type}-test",
            inst_type=inst_type,
            captured_at=datetime.now(UTC).isoformat(),
        )
        rows = await self.data_client.get_tickers(inst_type)
        from decimal import Decimal as D

        from crypto_trader.market_data.universe import Layer1Fact

        for raw in rows:
            batch.facts.append(Layer1Fact(
                inst_id=raw["instId"], inst_type=inst_type,
                last=raw.get("last", "NOT_AVAILABLE"),
                bid=raw.get("bidPx", "NOT_AVAILABLE"),
                ask=raw.get("askPx", "NOT_AVAILABLE"),
                volume_24h=raw.get("vol24h", "NOT_AVAILABLE"),
                volume_ccy_24h=raw.get("volCcy24h", "NOT_AVAILABLE"),
                timestamp=raw.get("ts", ""),
                freshness="LIVE",
            ))
        _ = D
        return batch


async def test_layer1_batch_scan_one_call_per_class():
    client = FakeDataClient()
    obs = _observer(client)
    await obs.poll(force=True)
    assert sorted(client.calls) == ["SPOT", "SWAP"], "one batch per product class"
    summary = obs.observe()
    assert summary["available"] is True
    assert summary["market_breadth"]["SPOT"]["instruments"] == 2
    assert summary["market_breadth"]["SWAP"]["two_sided_quotes"] == 2
    assert summary["source"] == "REST"


async def test_pinned_candidates_kept_without_ai_configuration():
    """P1 CS-20260830-034530-P3-AI-ATTENTION: with no attention selector the
    dynamic slots stay EMPTY (honest AI_NOT_CONFIGURED) -- the volume Top-K
    must never silently return. Held/core pins are still protected."""
    client = FakeDataClient()
    obs = _observer(client)
    await obs.poll(force=True)
    cand = await obs.select_candidates(
        target=2,
        held_canonical_symbols=("TRXUSDT",),
        core_canonical_symbols=("BTCUSDT",),
    )
    # pinned first (held + core); NO volume-ranked dynamic fills
    assert cand.inst_ids[0] == "TRX-USDT"
    assert "BTC-USDT" in cand.inst_ids or "BTC-USDT-SWAP" in cand.inst_ids
    assert "DOGE-USDT-SWAP" not in cand.inst_ids, "no volume-rank fallback"
    assert cand.attention is not None
    assert cand.attention.mode == "AI_NOT_CONFIGURED"
    assert cand.basis["rule"].startswith("held+core pinned")
    assert "attention_uid" in cand.basis


class _StubAttentionSelector:
    """Deterministic AI attention stub (test-only; production uses the LLM)."""

    version = "stub-1.0.0"

    def __init__(self, picks):
        self.picks = list(picks)

    async def select(self, digest, *, slots, pinned_inst_ids=()):
        roster = [row["inst_id"] for row in digest.get("roster") or []]
        selected = [i for i in self.picks if i in set(roster) | set(pinned_inst_ids)]
        return tuple(selected[: max(0, slots)]), {
            "mode": "AI_SELECTED",
            "rationale": "stub deterministic attention",
            "llm_invocation_id": "llm-stub-1",
            "error": "",
            "roster_size": len(roster),
        }


async def test_ai_attention_selection_replaces_volume_rank():
    client = FakeDataClient()
    obs = _observer(client)
    obs.attention_selector = _StubAttentionSelector(["TRX-USDT"])
    await obs.poll(force=True)
    cand = await obs.select_candidates(
        target=3,
        held_canonical_symbols=(),
        core_canonical_symbols=("BTCUSDT",),
    )
    assert "TRX-USDT" in cand.inst_ids
    assert "DOGE-USDT-SWAP" not in cand.inst_ids, "AI output, not volume rank"
    assert cand.attention.mode == "AI_SELECTED"
    assert cand.attention.llm_invocation_id == "llm-stub-1"


async def test_stale_marking_and_no_fabrication():
    t = {"now": 1000.0}

    def clock():
        return t["now"]

    client = FakeDataClient()
    obs = _observer(client, clock=clock)
    await obs.poll(force=True)
    assert obs._fact_freshness("SPOT") == "LIVE"
    # advance past staleness and make the network fail
    t["now"] += 10_000.0
    client.fail = True
    await obs.poll(force=True)
    assert obs._fact_freshness("SPOT") == "STALE"
    summary = obs.observe()
    assert summary["available"] is True, "previous batch still usable, marked stale"
    assert summary["market_breadth"]["SPOT"]["freshness"] == "STALE"
    assert summary.get("last_error"), "failure recorded, never silent"


async def test_ws_candidate_set_bounded_and_fallback_mode():
    ws = OKXTickerWsManager()
    ws._latest = {f"INST-{i}": {"last": "1"} for i in range(80)}
    ws._last_msg_mono = 0.0  # long ago -> unhealthy -> FALLBACK
    assert ws.mode == "FALLBACK"
    client = FakeDataClient()
    obs = _observer(client)
    obs.attention_selector = _StubAttentionSelector(
        [f"INST-{i}" for i in range(80)]  # over-selecting AI is still bounded
    )
    obs.ws_manager = ws
    await obs.poll(force=True)
    cand = await obs.select_candidates(target=60)  # over target cap
    assert len(cand.inst_ids) <= 50, "WS subscription bounded"
    summary = obs.observe(cand)
    assert summary["source"] == "FALLBACK"


def _adapter(observer):
    return MultiSymbolChiefTraderStrategyAdapter(
        symbols=("BTCUSDT", "ETHUSDT"),
        provider=None,
        market_observer=observer,
    )


async def test_dynamic_rotation_core_retained_and_bounded():
    client = FakeDataClient()
    obs = _observer(client)
    await obs.poll(force=True)
    adapter = _adapter(obs)
    assert set(adapter.symbols) == {"BTCUSDT", "ETHUSDT"}
    adapter._dynamic_symbols = ("TRXUSDT", "DOGEUSDT", "BTCUSDT")
    rotation = adapter.rotation_symbols
    assert rotation[:2] == ("BTCUSDT", "ETHUSDT"), "core always first/retained"
    assert len(rotation) == 4, "deduplicated"
    assert len(set(rotation)) == len(rotation)


async def test_observer_failure_is_fail_open(database):
    """ADVISORY_ONLY: an observer that raises must not break the decision
    context build and must not inject the key."""
    class ExplodingObserver:
        async def select_candidates(self, *a, **k):
            raise RuntimeError("boom")

        def update_ws_candidates(self, cand):
            pass

        def canonical_symbols_for(self, cand):
            return ()

        def observe(self, cand=None):
            return {}

    adapter = _adapter(ExplodingObserver())

    class ChiefCtx:
        strategy_evidence: dict = {}
        portfolio_state: dict = {}

    await adapter._refresh_market_observer(ChiefCtx())
    assert "market_observer" not in ChiefCtx.strategy_evidence
    assert adapter._observer_failures == 1


async def test_observer_evidence_injected_and_rotation_updated():
    client = FakeDataClient()
    obs = _observer(client)
    await obs.poll(force=True)
    adapter = _adapter(obs)

    class ChiefCtx:
        strategy_evidence: dict = {}
        portfolio_state: dict = {"positions": {"TRXUSDT": {"quantity": "0.001"}}}

    await adapter._refresh_market_observer(ChiefCtx())
    summary = ChiefCtx.strategy_evidence.get("market_observer")
    assert summary is not None and summary["available"] is True
    assert "TRX-USDT" in summary["candidates"]["facts"]
    assert "TRXUSDT" in adapter.dynamic_symbols, "held position pinned into rotation"
    assert summary.get("attention", {}).get("mode") == "AI_NOT_CONFIGURED"


async def test_engine_snapshot_exposes_observer(database):
    from tests.integration.test_perpetual_runtime_routing import _make_bundle

    client = FakeDataClient()
    obs = _observer(client)
    bundle = await _make_bundle(database)
    try:
        bundle.engine.market_observer = obs
        await obs.poll(force=True)
        snap = bundle.engine.runtime_snapshot()
        assert "market_observer" in snap
        assert snap["market_observer"]["available"] is True
    finally:
        await bundle.engine.stop()
