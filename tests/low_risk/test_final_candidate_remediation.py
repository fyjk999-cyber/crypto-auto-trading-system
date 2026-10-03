"""Regressions for the durable-state and tool-router remediation candidate."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from crypto_trader.llm.tools.registry import (
    CANONICAL_MAX_SELECTED_TOOLS,
    MAX_SELECTED_TOOLS,
    LLMToolRegistry,
)
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.engine import ChiefTraderEngine, ToolSelection
from crypto_trader.llm_chief.tool_orchestrator import ToolDrivenChiefTrader
from crypto_trader.runtime.durability import (
    ensure_durable_state_path,
    is_ephemeral_path,
    sqlite_path_from_url,
)


class _Response:
    text = ""
    error = None

    def __init__(self, tools):
        self.ok = True
        self.parsed_json = {"tools": tools}


def _ctx() -> ChiefTraderContext:
    return ChiefTraderContext(
        symbol="BTCUSDT",
        market_snapshot={"source": "OKX_PUBLIC"},
        regime="RANGE",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
    )


def test_schema_max_equals_registry_max():
    assert MAX_SELECTED_TOOLS == CANONICAL_MAX_SELECTED_TOOLS
    assert ToolSelection(tools=[f"t{i}" for i in range(CANONICAL_MAX_SELECTED_TOOLS)])
    with pytest.raises(ValidationError):
        ToolSelection(tools=[f"t{i}" for i in range(CANONICAL_MAX_SELECTED_TOOLS + 1)])


def test_validation_accepts_exact_limit_and_rejects_over_limit_before_build():
    available = [f"tool:{i}" for i in range(20)]
    selected, error, detail = ChiefTraderEngine._validate_tool_selection(
        _Response(available[:CANONICAL_MAX_SELECTED_TOOLS]), available
    )
    assert error is None
    assert len(selected) == CANONICAL_MAX_SELECTED_TOOLS

    selected9, error9, detail9 = ChiefTraderEngine._validate_tool_selection(
        _Response(available[: CANONICAL_MAX_SELECTED_TOOLS + 1]), available
    )
    assert selected9 is None
    assert error9 == "TOOL_COUNT_LIMIT_EXCEEDED"
    assert f"selected={CANONICAL_MAX_SELECTED_TOOLS + 1}" in detail9
    assert f"limit={CANONICAL_MAX_SELECTED_TOOLS}" in detail9

    selected12, error12, _ = ChiefTraderEngine._validate_tool_selection(
        _Response(available[:12]), available
    )
    assert selected12 is None
    assert error12 == "TOOL_COUNT_LIMIT_EXCEEDED"


async def test_registry_rejects_over_limit_without_truncation():
    registry = LLMToolRegistry()

    async def tool(symbol: str, _ctx):
        raise AssertionError("tool must not run when package limit is exceeded")

    names = [f"tool:{i}" for i in range(CANONICAL_MAX_SELECTED_TOOLS + 1)]
    for name in names:
        registry.register(name, tool)
    with pytest.raises(ValueError, match="tool budget exceeded"):
        await registry.build_package(names, "BTCUSDT", {}, now=datetime.now(UTC))


class _FailingChief:
    def __init__(self) -> None:
        self.fail_reason: str | None = None

    async def select_tools(self, _ctx, _available):
        return ["tool:0"] * CANONICAL_MAX_SELECTED_TOOLS, None

    def fail_closed(self, ctx, reason):
        self.fail_reason = reason
        return ChiefTraderDecision(
            decision_id="d1",
            symbol=ctx.symbol,
            action="FAIL_CLOSED",
            market_regime=ctx.regime,
            reason_codes=[reason],
        )


class _OverLimitTools:
    def available(self):
        return ["tool:0"]

    async def build_package(self, *_args, **_kwargs):
        raise ValueError("tool budget exceeded: selected=9 limit=8 SECRET_SHOULD_NOT_LEAK")


async def test_over_limit_router_failure_is_explicit_and_does_not_leak_secret():
    chief = _FailingChief()
    orchestrator = ToolDrivenChiefTrader(chief, _OverLimitTools())
    decision, package = await orchestrator.decide(
        _ctx(), tool_context={}, now=datetime.now(UTC)
    )
    assert package is None
    assert decision.action == "FAIL_CLOSED"
    assert chief.fail_reason is not None
    assert chief.fail_reason.startswith("TOOL_COUNT_LIMIT_EXCEEDED")
    assert "stage=build_package" in chief.fail_reason
    assert "error_class=ValueError" in chief.fail_reason
    assert f"selected={CANONICAL_MAX_SELECTED_TOOLS}" in chief.fail_reason
    assert "SECRET_SHOULD_NOT_LEAK" not in chief.fail_reason


def test_ephemeral_canonical_db_is_rejected():
    path = "/private/tmp/lr2-soak2/data/crypto_trader.db"
    assert is_ephemeral_path(Path(path)) is True
    with pytest.raises(ValueError, match="EPHEMERAL_CANONICAL_DB=BLOCKED"):
        ensure_durable_state_path(f"sqlite+aiosqlite:///{path}")


def test_durable_canonical_db_accepted_and_parent_created():
    durable = Path.home() / "Library" / "Application Support" / "LowRisk" / "tests" / "runtime"
    db = durable / "crypto_trader_test.db"
    try:
        resolved = ensure_durable_state_path(
            f"sqlite+aiosqlite:///{db}", allow_ephemeral=False, create_parent=True
        )
        assert resolved == db
        assert db.parent.is_dir()
        assert sqlite_path_from_url(f"sqlite+aiosqlite:///{db}") == db
    finally:
        try:
            db.unlink(missing_ok=True)
            db.parent.rmdir()
            db.parent.parent.rmdir()
        except OSError:
            pass

