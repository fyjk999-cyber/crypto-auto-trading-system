"""Cross-subsystem regressions for the final Low-Risk V2 convergence.

These tests bind the merged semantics that cannot be owned by any single
pre-convergence branch: provider durability + Flash High, runtime
constitution + hedge switch, ML self-input exclusion, News/Growth evidence
authority and the single Alembic head.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager
from crypto_trader.llm_chief.provider import (
    DeepSeekProvider,
    resolve_trading_llm_config,
    resolve_trading_model,
)
from crypto_trader.market_data.opportunity.snapshots import (
    MODEL_25_ID,
    freeze_model_evidence,
)
from crypto_trader.runtime.bootstrap import leg_execution_enabled_from_env
from crypto_trader.runtime.engine import TradingEngine

ROOT = Path(__file__).resolve().parents[2]


def test_final_convergence_has_exactly_one_migration_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert list(script.get_heads()) == ["0043_research_scope"]


def test_flash_high_wins_and_provider_policy_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_LLM_MODEL", "deepseek-flash")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-pro")
    cfg = resolve_trading_llm_config()
    assert cfg.provider == "deepseek"
    assert cfg.model == "deepseek-flash"
    assert cfg.thinking is True
    assert cfg.reasoning_effort == "high"
    assert DeepSeekProvider(api_key="test").model == "deepseek-flash"

    monkeypatch.delenv("TRADING_LLM_MODEL")
    with pytest.raises(ValueError):
        resolve_trading_model()
    provider = DeepSeekProvider(api_key="test-secret")
    assert provider.healthy() is False
    assert provider.diagnostics()["configuration_error"] == (
        "forbidden production LLM_MODEL: deepseek-v4-pro"
    )


def test_runtime_constitution_replaces_time_stop_with_reassessment() -> None:
    position_manager_source = inspect.getsource(LiveLLMPositionManager)
    engine_source = inspect.getsource(TradingEngine)
    assert "TIME_STOP_SAFETY_FALLBACK" not in position_manager_source
    assert "expected_holding_horizon_reached" in position_manager_source
    assert "TIME_STOP_SAFETY_FALLBACK" not in engine_source
    assert "ReassessmentEvaluator" in engine_source
    assert "NEXT_REASSESSMENT_WAKE" in engine_source


def test_open_position_review_priority_and_deadline_are_wired() -> None:
    engine_source = inspect.getsource(TradingEngine)
    manager_source = inspect.getsource(LiveLLMPositionManager)
    assert "review_priority" in engine_source
    assert "POSITION_REVIEW_DEADLINE_EXCEEDED" in engine_source
    assert "def review_priority" in manager_source


def test_hedge_switch_is_configurable_and_news_runtime_is_wired(monkeypatch) -> None:
    monkeypatch.delenv("LEG_EXECUTION_ENABLED", raising=False)
    assert leg_execution_enabled_from_env() is False
    monkeypatch.setenv("LEG_EXECUTION_ENABLED", "true")
    assert leg_execution_enabled_from_env() is True
    bootstrap_source = inspect.getsource(
        __import__("crypto_trader.runtime.bootstrap", fromlist=["build_system"])
    )
    assert "engine.leg_execution_enabled = leg_execution_enabled_from_env()" in bootstrap_source
    assert "NewsReassessmentRuntime" in bootstrap_source


def test_ml_evidence_excludes_25_self_input_and_old_labels_are_archival() -> None:
    frozen = freeze_model_evidence(
        [
            {"model_id": MODEL_25_ID, "direction": "LONG", "available": True},
            {"model_id": "01_TREND", "direction": "SHORT", "available": True},
        ]
    )
    assert [item["model_id"] for item in frozen] == ["01_TREND"]

    from crypto_trader import ml_dataset

    assert ml_dataset.FINAL_LABEL_VERSION == "label-v2"


def test_growth_and_news_remain_evidence_only() -> None:
    growth_source = (ROOT / "src/crypto_trader/growth_status.py").read_text()
    news_source = (ROOT / "src/crypto_trader/news/status.py").read_text()
    assert "can_modify_core" in growth_source
    assert "LEARNING_ONLY" in growth_source
    assert "EVIDENCE_ONLY" in news_source
    assert "is_order" in news_source
    assert inspect.getsource(ChiefTraderEngine)  # canonical Core-LLM decision owner


def test_paper_wrapper_enables_leg_execution_for_natural_evidence() -> None:
    wrapper = (ROOT / "scripts" / "run_low_risk_paper_secure.sh").read_text()
    assert "LEG_EXECUTION_ENABLED" in wrapper
    assert "true" in wrapper
    assert "LIVE_TRADING_ENABLED=false" in wrapper
