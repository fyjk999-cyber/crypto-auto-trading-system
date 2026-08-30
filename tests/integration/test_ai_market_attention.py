"""P1 CS-20260830-034530-P3-AI-ATTENTION acceptance tests.

Directive coverage:
NO_RANK_AUTHORITY      : a non-legacy, low-volume but LIVE instrument reaches
                         Market Observer AI consideration without any
                         quantitative eligibility veto
REGISTRY_LINEAGE       : five random non-legacy live instruments prove
                         registry -> Layer-1 -> observer-input lineage
AI_OWNS_ROTATION       : AI attention output (not volume rank) changes the
                         bounded dynamic Chief Trader rotation; stale/
                         unavailable instruments stay safely excluded
FAIL_OPEN_NO_RANK      : AI unavailable -> dynamic slots empty, trading
                         continues, NO volume-rank fallback
LINEAGE_PERSISTED      : attention decisions persisted with source evidence
                         and decision ids (no fabricated order/fill data)
EVIDENCE_IN_DECISION   : chief trader decision evidence carries the attention
                         lineage (attention_uid, mode, selection)
"""

import random
import sqlite3
from datetime import UTC, datetime

from crypto_trader.market_data.attention import (
    LLMMarketAttentionSelector,
    build_market_digest,
)
from crypto_trader.market_data.observer import HierarchicalMarketObserver
from crypto_trader.market_data.universe import MarketSnapshotBatch
from crypto_trader.persistence.models import MarketAttentionDecisionORM
from crypto_trader.runtime.multi_symbol_chief_trader import (
    MultiSymbolChiefTraderStrategyAdapter,
)

# ---------------------------------------------------------------- helpers


class _ScriptedLLM:
    """Scripted attention LLM: records the prompt, returns canned JSON."""

    version = "scripted-1.0.0"

    def __init__(self, response: dict | None = None, fail: bool = False):
        self.response = response
        self.fail = fail
        self.prompts: list[str] = []

    async def __call__(self, *, prompt: str):
        self.prompts.append(prompt)

        class _Resp:
            ok = not self.fail
            parsed_json = self.response or {}
            invocation_id = "llm-att-inv-1"
            error = "LLM_DOWN" if self.fail else None

        if self.fail:
            _Resp.ok = False
        return _Resp()


def _fact(inst_id: str, inst_type: str, *, last: str, low: str, high: str,
          vol_ccy: str = "1000", quote: bool = True):
    from crypto_trader.market_data.universe import Layer1Fact

    return Layer1Fact(
        inst_id=inst_id,
        inst_type=inst_type,
        last=last,
        bid=str(float(last) * 0.999) if quote else "NOT_AVAILABLE",
        ask=str(float(last) * 1.001) if quote else "NOT_AVAILABLE",
        high_24h=high,
        low_24h=low,
        volume_24h="1",
        volume_ccy_24h=vol_ccy,
        freshness="LIVE",
    )


def _observer(facts_by_type: dict[str, list], *, selector=None, **kwargs):
    class _Universe:
        async def layer1_batch(self, inst_type):
            batch = MarketSnapshotBatch(
                batch_id=f"l1-{inst_type}-att-test",
                inst_type=inst_type,
                captured_at=datetime.now(UTC).isoformat(),
            )
            batch.facts = facts_by_type.get(inst_type, [])
            return batch

    return HierarchicalMarketObserver(
        _Universe(), ws_manager=None, attention_selector=selector, **kwargs
    )


# ------------------------------------------------------------- NO_RANK_AUTHORITY


async def test_low_volume_live_instrument_reaches_ai_without_quant_veto():
    """A low-volume instrument must reach AI consideration exactly like a
    high-volume one: volume appears as evidence, never as eligibility."""
    tiny = _fact("ZZZ-USDT", "SPOT", last="0.00012", low="0.0001",
                 high="0.0002", vol_ccy="0.5")
    huge = _fact("BTC-USDT", "SPOT", last="60000", low="58000", high="62000",
                 vol_ccy="900000000")
    obs = _observer({"SPOT": [huge, tiny]})
    await obs.poll(force=True)
    llm = _ScriptedLLM()
    obs.attention_selector = LLMMarketAttentionSelector(llm)
    digest = build_market_digest(
        obs._batches,
        freshness_by_type={"SPOT": "LIVE", "SWAP": "NOT_AVAILABLE"},
        pinned_inst_ids=(),
    )
    roster_ids = {row["inst_id"] for row in digest["roster"]}
    assert "ZZZ-USDT" in roster_ids, "low-volume instrument must reach AI input"
    assert "BTC-USDT" in roster_ids
    # volume is attached as evidence only
    zzz = next(r for r in digest["roster"] if r["inst_id"] == "ZZZ-USDT")
    assert zzz["vol_ccy_24h"] == "0.5"
    # and the AI can legitimately select it
    obs.attention_selector = LLMMarketAttentionSelector(
        _ScriptedLLM({"selected": ["ZZZ-USDT"], "rationale": "range-top evidence"})
    )
    cand = await obs.select_candidates(target=2, core_canonical_symbols=("BTCUSDT",))
    assert "ZZZ-USDT" in cand.inst_ids
    assert cand.attention.mode == "AI_SELECTED"


async def test_ai_selection_may_ignore_high_volume_instruments():
    """AI attention output -- not volume rank -- decides the rotation."""
    facts = [
        _fact("BTC-USDT", "SPOT", last="60000", low="58000", high="62000",
              vol_ccy="900000000"),
        _fact("AAA-USDT", "SPOT", last="1.0", low="0.9", high="1.1",
              vol_ccy="10"),
    ]
    obs = _observer({"SPOT": facts})
    await obs.poll(force=True)
    # scripted AI picks ONLY the tiny instrument
    obs.attention_selector = LLMMarketAttentionSelector(
        _ScriptedLLM({"selected": ["AAA-USDT"], "rationale": "diversity"})
    )
    cand = await obs.select_candidates(target=2)
    assert "AAA-USDT" in cand.inst_ids
    assert "BTC-USDT" not in cand.inst_ids, (
        "the high-volume instrument must NOT be auto-included by rank"
    )


# ------------------------------------------------------------- REGISTRY_LINEAGE


def _seed_registry(db_path: str, inst_ids: list[tuple[str, str]]) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS okx_instruments (inst_id TEXT PRIMARY KEY, "
            "inst_type TEXT, state TEXT, base_ccy TEXT, quote_ccy TEXT)"
        )
        for inst_id, inst_type in inst_ids:
            conn.execute(
                "INSERT OR REPLACE INTO okx_instruments "
                "(inst_id, inst_type, state, base_ccy, quote_ccy) "
                "VALUES (?, ?, 'live', ?, 'USDT')",
                (inst_id, inst_type, inst_id.split("-")[0]),
            )
        conn.commit()
    finally:
        conn.close()


async def test_five_random_live_instruments_reach_observer_input(tmp_path):
    """Registry -> Layer-1 -> observer input lineage for 5 random live
    instruments (seeded RNG; deterministic but arbitrary). The bounded
    roster rotates its stride window each refresh, so every instrument gets
    AI-consideration turns; here we prove each sampled instrument is covered
    by bucket counts at every offset AND enters the roster within one full
    rotation of its bucket."""
    from crypto_trader.market_data.universe import DynamicMarketUniverse

    inst_ids = [(f"SYM{i}-USDT", "SPOT") for i in range(40)]
    db_path = str(tmp_path / "registry.db")
    _seed_registry(db_path, inst_ids)

    class _Client:
        async def get_tickers(self, inst_type, uly=None):
            if inst_type != "SPOT":
                return []
            return [
                {
                    "instId": inst_id,
                    "last": str(1.0 + i),
                    "bidPx": str(1.0 + i - 0.001),
                    "askPx": str(1.0 + i + 0.001),
                    "high24h": str(1.0 + i + 0.5),
                    "low24h": str(1.0 + i - 0.5),
                    "vol24h": "1",
                    "volCcy24h": "100",
                    "ts": "1",
                }
                for i, (inst_id, _itype) in enumerate(inst_ids)
            ]

    universe = DynamicMarketUniverse(db_path, data_client=_Client())
    registered = {row["inst_id"] for row in universe.observable_universe()}
    assert len(registered) == 40, "registry truth loaded"

    rng = random.Random(20260830)
    sample = rng.sample(sorted(registered), 5)
    obs = HierarchicalMarketObserver(universe, ws_manager=None)
    await obs.poll(force=True)
    all_roster_ids: set[str] = set()
    for offset in range(8):  # >= ceil(40/7) blocks -> full bucket rotation
        digest = build_market_digest(
            obs._batches,
            freshness_by_type={t: obs._fact_freshness(t) for t in ("SPOT", "SWAP")},
            rotation_offset=offset,
        )
        bucketed = sum(v["count"] for v in digest["buckets"].values())
        assert bucketed == 40, "every live instrument is covered by bucket counts"
        assert len(digest["roster"]) <= 60, "roster stays bounded"
        all_roster_ids |= {r["inst_id"] for r in digest["roster"]}
    for inst_id in sample:
        assert inst_id in registered, "registry lineage"
        assert inst_id in all_roster_ids, (
            f"{inst_id} must reach the observer input within one rotation"
        )


# --------------------------------------------------------- AI_OWNS_ROTATION


async def test_stale_and_unavailable_instruments_safely_excluded():
    facts = [
        _fact("BTC-USDT", "SPOT", last="100", low="90", high="110"),
        _fact("NOQ-USDT", "SPOT", last="5", low="4", high="6", quote=False),
    ]
    obs = _observer({"SPOT": facts})
    await obs.poll(force=True)
    digest = build_market_digest(
        obs._batches,
        freshness_by_type={"SPOT": "LIVE", "SWAP": "NOT_AVAILABLE"},
    )
    assert digest["buckets"]["NO_QUOTE"]["count"] == 1
    assert digest["universe"]["unavailable_no_quote"] == 1
    roster_ids = {r["inst_id"] for r in digest["roster"]}
    assert "NOQ-USDT" not in roster_ids, "unavailable instrument not selectable"

    # stale batch: everything marked stale, roster empties (availability)
    obs2 = _observer({"SPOT": facts})
    t = {"now": 1000.0}
    obs2.clock = lambda: t["now"]
    await obs2.poll(force=True)
    t["now"] += 10_000.0  # past stale threshold
    digest2 = build_market_digest(
        obs2._batches,
        freshness_by_type={tt: obs2._fact_freshness(tt) for tt in ("SPOT", "SWAP")},
    )
    assert all(r["freshness"] == "STALE" for r in digest2["roster"]) or not digest2["roster"]


async def test_ai_unavailable_fails_open_without_rank_fallback():
    facts = [
        _fact("BTC-USDT", "SPOT", last="100", low="90", high="110"),
        _fact("LOWVOL-USDT", "SPOT", last="1", low="0.9", high="1.1", vol_ccy="0.1"),
    ]
    obs = _observer({"SPOT": facts})
    await obs.poll(force=True)
    obs.attention_selector = LLMMarketAttentionSelector(_ScriptedLLM(fail=True))
    cand = await obs.select_candidates(target=5)
    assert cand.attention.mode == "AI_UNAVAILABLE"
    assert cand.attention.error
    assert list(cand.inst_ids) == [], (
        "no dynamic slots when AI unavailable -- and NO volume-rank fallback"
    )
    summary = obs.observe(cand)
    assert summary["available"] is True  # evidence still flows, fail-open


async def test_attention_refresh_throttled_and_carried_forward():
    facts = [_fact("BTC-USDT", "SPOT", last="100", low="90", high="110")]
    t = {"now": 1000.0}
    obs = _observer({"SPOT": facts}, attention_refresh_seconds=300.0)
    obs.clock = lambda: t["now"]
    await obs.poll(force=True)
    selector = LLMMarketAttentionSelector(
        _ScriptedLLM({"selected": ["BTC-USDT"], "rationale": "r"})
    )
    obs.attention_selector = selector
    first = await obs.select_candidates(target=2)
    assert first.attention.cache_state == "REFRESH"
    calls_after_first = len(selector._complete_json.prompts)
    second = await obs.select_candidates(target=2)
    assert second.attention.attention_uid == first.attention.attention_uid, (
        "within the refresh window the previous AI selection is reused"
    )
    assert len(selector._complete_json.prompts) == calls_after_first
    # after the window, a refresh happens
    t["now"] += 400.0
    third = await obs.select_candidates(target=2)
    assert len(selector._complete_json.prompts) == calls_after_first + 1
    assert third.attention.attention_uid != first.attention.attention_uid


async def test_ai_selected_outside_roster_is_dropped():
    facts = [_fact("BTC-USDT", "SPOT", last="100", low="90", high="110")]
    obs = _observer({"SPOT": facts})
    await obs.poll(force=True)
    obs.attention_selector = LLMMarketAttentionSelector(
        _ScriptedLLM({"selected": ["BTC-USDT", "FAKE-USDT"], "rationale": "r"})
    )
    cand = await obs.select_candidates(target=5)
    assert "FAKE-USDT" not in cand.inst_ids, "hallucinated instruments dropped"
    assert "BTC-USDT" in cand.inst_ids


# ------------------------------------------------------- LINEAGE_PERSISTED


async def test_attention_lineage_persisted_with_source_evidence(database):
    """Attention rows persist durably (ORM) and carry source evidence."""
    from sqlalchemy import select

    persisted: list[str] = []

    async def sink(row: dict) -> None:
        async with database.session_factory() as session:
            session.add(MarketAttentionDecisionORM(**row))
            await session.commit()
        persisted.append(row["attention_uid"])

    facts = [
        _fact("BTC-USDT", "SPOT", last="100", low="90", high="110"),
        _fact("ETH-USDT", "SPOT", last="2000", low="1900", high="2100"),
    ]
    obs = _observer({"SPOT": facts}, attention_lineage_sink=sink)
    await obs.poll(force=True)
    obs.attention_selector = LLMMarketAttentionSelector(
        _ScriptedLLM({"selected": ["ETH-USDT"], "rationale": "range evidence"})
    )
    await obs.select_candidates(target=2, core_canonical_symbols=("BTCUSDT",))
    assert len(persisted) == 1
    async with database.session_factory() as session:
        orm_row = (
            await session.execute(
                select(MarketAttentionDecisionORM).order_by(
                    MarketAttentionDecisionORM.id.desc()
                )
            )
        ).scalars().first()
    assert orm_row is not None
    assert orm_row.mode == "AI_SELECTED"
    assert orm_row.selected_inst_ids == ["ETH-USDT"]
    assert orm_row.pinned_inst_ids == ["BTC-USDT"]
    assert orm_row.universe_size == 2
    assert orm_row.input_digest
    assert orm_row.llm_invocation_id == "llm-att-inv-1"
    assert orm_row.layer1_batch_ids.get("SPOT") == "l1-SPOT-att-test"
    assert orm_row.attention_uid == persisted[0]
    # the bounded projection used in decision evidence matches
    proj = obs._last_attention.to_bounded_dict()
    assert proj["attention_uid"] == orm_row.attention_uid


async def test_attention_lineage_in_chief_trader_decision_evidence(database):
    """Full decision-path linkage: attention uid reaches DecisionEvidence."""

    from crypto_trader.governance.tool_journal import ToolInvocationJournal

    journal = ToolInvocationJournal(database.session_factory)
    facts = [_fact("BTC-USDT", "SPOT", last="100", low="90", high="110")]
    obs = _observer({"SPOT": facts})
    await obs.poll(force=True)
    obs.attention_selector = LLMMarketAttentionSelector(
        _ScriptedLLM({"selected": ["BTC-USDT"], "rationale": "r"})
    )
    adapter = MultiSymbolChiefTraderStrategyAdapter(
        symbols=("BTCUSDT",),
        provider=None,
        market_observer=obs,
        tool_journal=journal,
    )
    class ChiefCtx:
        symbol = "BTCUSDT"
        strategy_evidence: dict = {}
        portfolio_state: dict = {"positions": {}}

    await adapter._refresh_market_observer(ChiefCtx())
    summary = ChiefCtx.strategy_evidence["market_observer"]
    attention = summary["attention"]
    assert attention["mode"] == "AI_SELECTED"
    assert attention["attention_uid"].startswith("att-")
    assert "BTC-USDT" in attention["selected_inst_ids"]
    assert "BTCUSDT" in adapter.dynamic_symbols
    # the attention invocation is journaled for the decision trace
    assert any(r["tool_name"] == "market_observer_ai" for r in journal._buffer)
    row = next(r for r in journal._buffer if r["tool_name"] == "market_observer_ai")
    assert row["status"] == "OK"
    assert attention["attention_uid"][:20] in row["detail"]


def test_digest_is_bounded_and_covers_whole_universe():
    facts = [
        _fact(f"S{i}-USDT", "SPOT", last=str(100 + i), low="90", high="110")
        for i in range(500)
    ]
    digest = build_market_digest(
        {"SPOT": MarketSnapshotBatch(
            batch_id="b1", inst_type="SPOT",
            captured_at=datetime.now(UTC).isoformat(), facts=facts)},
        freshness_by_type={"SPOT": "LIVE", "SWAP": "NOT_AVAILABLE"},
    )
    total_count = sum(v["count"] for v in digest["buckets"].values())
    assert total_count == 500, "compression covers the WHOLE universe"
    assert len(digest["roster"]) <= 60, "roster is bounded"
    assert len(digest["input_digest"]) == 32


async def test_bound_contract_is_pinned_plus_target_dynamic_slots():
    """The P3 correction must NOT shrink the candidate bound: pinned held/
    core are always retained and the AI still receives ``target`` dynamic
    slots on top of them (pre-P3 contract)."""
    facts = [_fact("BTC-USDT", "SPOT", last="100", low="90", high="110")]
    obs = _observer({"SPOT": facts})
    await obs.poll(force=True)
    obs.attention_selector = LLMMarketAttentionSelector(
        _ScriptedLLM({"selected": ["BTC-USDT"], "rationale": "r"})
    )
    cand = await obs.select_candidates(
        target=5, held_canonical_symbols=("BTCUSDT",)
    )
    assert cand.attention.mode == "AI_SELECTED"
    assert cand.basis["target"] == 5
    assert "BTC-USDT" in cand.inst_ids
    assert cand.basis["roster_size"] > 0, "AI received a non-empty roster"
