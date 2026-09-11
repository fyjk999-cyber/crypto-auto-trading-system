"""V2 invariant tests: cards are evidence only; Risk/Execution untouched."""

from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy import func, select

from crypto_trader.learning.growth_card_retrieval import (
    ExperienceCardRetriever,
    register_experience_card_tool,
)
from crypto_trader.learning.growth_experience import AdaptiveCardStore
from crypto_trader.learning.growth_v2_contracts import (
    AdaptiveExperienceCard,
    CardUpdateProposal,
)
from crypto_trader.llm.tools.registry import LLMToolRegistry
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.persistence.models import FillORM, OrderORM, TradeEpisodeORM
from tests.growth_system_v2.conftest import AS_OF, market_context, seed_card

V2_MODULES = (
    "growth_v2_contracts.py",
    "growth_card_view.py",
    "growth_card_quality.py",
    "growth_experience.py",
    "growth_card_retrieval.py",
    "growth_attribution.py",
    "growth_v2_migration.py",
)

FORBIDDEN_IMPORT_PREFIXES = (
    "crypto_trader.risk",
    "crypto_trader.execution",
    "crypto_trader.order",
    "crypto_trader.exchange",
    "crypto_trader.runtime",
    "crypto_trader.simulator",
)

FORBIDDEN_NAMES = (
    "submit_order",
    "place_order",
    "create_fill",
    "execute_order",
    "mutate_position",
    "set_leverage",
    "disable_kill_switch",
    "approve_risk",
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_v2_modules_never_import_risk_execution_or_runtime():
    root = Path(__file__).resolve().parents[2] / "src" / "crypto_trader" / "learning"
    for filename in V2_MODULES:
        imports = _imports(root / filename)
        for module in imports:
            assert not module.startswith(FORBIDDEN_IMPORT_PREFIXES), (
                f"{filename} imports forbidden authority module {module}"
            )


def test_v2_modules_do_not_define_authority_functions():
    root = Path(__file__).resolve().parents[2] / "src" / "crypto_trader" / "learning"
    for filename in V2_MODULES:
        text = (root / filename).read_text(encoding="utf-8")
        for name in FORBIDDEN_NAMES:
            assert name not in text, f"{filename} mentions forbidden authority {name}"


def test_card_domain_declares_evidence_only_semantics():
    card = AdaptiveExperienceCard(rule_id="card_sem", title="t", content="c")
    semantics = card.semantics()
    assert semantics["evidence_only"] is True
    assert semantics["can_emit_direction"] is False
    assert "NOT_COMMANDS" in semantics["prompt_semantics"]


async def test_card_operations_do_not_create_risk_execution_or_episode_artifacts(v2_db):
    from crypto_trader.risk.engine import RiskEngine

    before = RiskEngine().config.model_dump()
    await seed_card(v2_db, rule_id="card_invariant", status="ACTIVE")
    store = AdaptiveCardStore(v2_db.session_factory)
    await store.apply(
        CardUpdateProposal(
            operation="UPDATE",
            rationale="INVARIANT_TEST",
            card_rule_id="card_invariant",
            source_episode_ids=["ep_new"],
            supporting_episode_ids=["ep_new"],
        ).finalize()
    )
    after = RiskEngine().config.model_dump()
    assert before == after
    async with v2_db.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(OrderORM)) == 0
        assert await session.scalar(select(func.count()).select_from(FillORM)) == 0
        assert await session.scalar(select(func.count()).select_from(TradeEpisodeORM)) == 0


async def test_runtime_card_tool_has_no_direction_authority(v2_db):
    await seed_card(v2_db, rule_id="card_tool", status="ACTIVE")
    registry = LLMToolRegistry()
    register_experience_card_tool(
        registry, ExperienceCardRetriever(v2_db.session_factory)
    )
    evidence = await registry.call(
        "experience_cards",
        "BTCUSDT",
        {
            "as_of": AS_OF,
            "chief_context": ChiefTraderContext(
                symbol="BTCUSDT",
                market_snapshot={},
                regime="BULL",
                quant_evidence=[],
                portfolio_state={},
                risk_summary={},
                prepared_at=AS_OF.isoformat(),
            ),
            "factor_states": [
                {
                    "factor_id": "funding_rate",
                    "state": "EXTREME_HIGH",
                    "definition_version": "funding-def-v1",
                },
                {
                    "factor_id": "open_interest",
                    "state": "RISING",
                    "definition_version": "oi-def-v1",
                },
            ],
            "market_state": market_context().to_json(),
        },
    )
    card = evidence.features["cards"][0]
    assert card["evidence_only"] is True
    assert card["can_emit_direction"] is False
    assert "action" not in card
    assert not hasattr(evidence, "action")
    # Retrieval/tool execution must not change the stored card version.
    stored = await AdaptiveCardStore(v2_db.session_factory).get_card("card_tool")
    assert stored.version == 1
