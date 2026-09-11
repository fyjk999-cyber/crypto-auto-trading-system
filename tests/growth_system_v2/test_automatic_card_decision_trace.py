"""Production-path proof: the canonical strategy auto-links the card decision trace.

The test drives ``LiveLLMDecisionStrategy.on_market_data()`` end to end:

    on_market_data -> ToolDrivenChiefTrader.decide (experience_cards tool)
    -> trace persisted BEFORE evidence use -> final ChiefTrader decision
    -> _attach_card_decision_trace -> CardDecisionTraceStore.attach_decision
    -> GrowthCardDecisionTraceORM linked to the final decision id

It MUST NOT call ``CardDecisionTraceStore.record``/``attach_decision`` or
``_attach_card_decision_trace`` itself: the production code owns the linkage.
Only the runtime-derived card context (normally built from live market state) is
supplied deterministically, mirroring an ACTIVE card whose trigger/context match.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select

from crypto_trader.learning.growth_card_retrieval import (
    CardDecisionTraceStore,
    ExperienceCardRetriever,
    register_experience_card_tool,
)
from crypto_trader.learning.growth_models import GrowthCardDecisionTraceORM
from crypto_trader.llm.tools.registry import LLMToolRegistry
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.runtime_strategy import LiveLLMDecisionStrategy
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader
from crypto_trader.persistence.models import FillORM, OrderORM
from tests.growth_system_v2.conftest import seed_card
from tests.growth_system_v2.test_chief_card_integration import (
    ScriptedProvider,
    _tool_context,
)
from tests.llm_chief.test_runtime_strategy import FakeEvidenceEngine, make_ctx


class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def log(self, action, **kwargs) -> None:
        self.events.append((action, kwargs))


async def test_live_strategy_automatically_links_retrieved_card_trace_to_final_decision(
    v2_db, monkeypatch
):
    await seed_card(v2_db, rule_id="card_auto_trace", status="ACTIVE")
    trace_store = CardDecisionTraceStore(v2_db.session_factory)
    registry = LLMToolRegistry()
    register_experience_card_tool(
        registry,
        ExperienceCardRetriever(v2_db.session_factory),
        trace_store=trace_store,
    )
    provider = ScriptedProvider(["experience_cards"])
    tool_chief = ToolDrivenChiefTrader(ChiefTraderEngine(provider=provider), registry)

    # The production runtime derives this context from live market state; the
    # test supplies the deterministic equivalent (ACTIVE card matches it).
    import crypto_trader.llm_chief.runtime_strategy as runtime_strategy

    monkeypatch.setattr(
        runtime_strategy, "build_card_tool_context", lambda ctx, **kwargs: _tool_context()
    )

    strategy = LiveLLMDecisionStrategy(
        evidence_engine=FakeEvidenceEngine(),
        chief=ChiefTraderEngine(provider=provider),
        planner=None,
        decisions=LLMDecisionStore(v2_db.session_factory),
        audit=_Audit(),
        tool_chief=tool_chief,
        card_trace_store=trace_store,
        card_account_id="default",
        card_mode="PAPER",
    )

    signals = await strategy.on_market_data(make_ctx())

    # NO_TRADE: the evidence path proves itself without sizing/execution.
    assert signals == []

    async with v2_db.session_factory() as session:
        traces = (await session.scalars(select(GrowthCardDecisionTraceORM))).all()
        orders = (await session.scalar(select(func.count()).select_from(OrderORM))) or 0
        fills = (await session.scalar(select(func.count()).select_from(FillORM))) or 0

    assert len(traces) == 1, "the production path must have created a trace"
    trace = traces[0]
    assert trace.trace_id
    assert trace.decision_id, "the production path must have linked the decision id"
    assert trace.account_id == "default"
    assert trace.mode == "PAPER"
    refs = list(trace.selected_card_refs_json or [])
    assert refs and any(str(ref).startswith("card:card_auto_trace") for ref in refs), refs
    assert refs == ["card:card_auto_trace:v1"], refs
    versions = trace.card_versions_json
    if isinstance(versions, str):
        versions = json.loads(versions)
    assert versions.get("card:card_auto_trace") == 1, versions

    # the linked decision is the one the canonical store persisted
    stored = await LLMDecisionStore(v2_db.session_factory).get(trace.decision_id)
    assert stored is not None
    assert str(stored.action) == "NO_TRADE"

    # cards are evidence only: no executable side effect
    assert orders == 0 and fills == 0
