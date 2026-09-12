from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LEGACY_PACKAGES = [
    "ai",
    "ai_agents",
    "ai_backtest",
    "ai_brain",
    "ai_certification",
    "ai_decision",
    "ai_memory",
    "ai_optimization",
    "ai_research_lab",
    "ai_risk",
    "ai_skill",
    "alpha_decay",
    "alpha_discovery",
    "alpha_intelligence",
    "blind_market_test",
    "calibration",
    "capital_guard",
    "capital_management",
    "capital_transition",
    "committee",
    "confidence_governor",
    "daily_report",
    "decision_replay",
    "deepseek",
    "demo",
    "exchange_intelligence",
    "execution_intelligence",
    "fund_management",
    "fund_simulation",
    "human_baseline",
    "investment_committee",
    "learning",
    "learning_coordinator",
    "llm_runtime",
    "market_history",
    "memory_governance",
    "memory_graph",
    "microstructure",
    "monitoring",
    "paper_training",
    "performance_attribution",
    "portfolio_risk",
    "position_manager",
    "prompt_evolution",
    "readiness",
    "regime_adaptation",
    "regime_forecast",
    "risk_personality",
    "scorecard",
    "self_critic",
    "shadow_campaign",
    "strategy_discovery",
    "strategy_lifecycle",
    "strategy_portfolio",
    "strategy_research",
    "style_engine",
    "training_scheduler",
    "validation_engine",
    "vector_memory"
]

ROOT = Path(__file__).resolve().parents[2]

def _active_files():
    roots = [ROOT / "src", ROOT / "tests", ROOT / "scripts", ROOT / "deploy", ROOT / ".github"]
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if "legacy_quarantine" in path.parts:
                continue
            if path.suffix in {".py", ".sh", ".toml", ".yml", ".yaml"}:
                yield path
    for name in ("pyproject.toml", "Dockerfile"):
        path = ROOT / name
        if path.exists():
            yield path

def test_no_active_ghost_references_to_quarantined_packages():
    offenders = []
    needles = {pkg: f"crypto_trader.{pkg}" for pkg in LEGACY_PACKAGES}
    needles["runtime_ai_position_bridge"] = "crypto_trader.runtime.ai_position_bridge"
    for path in _active_files():
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pkg, needle in needles.items():
            if needle in text:
                offenders.append(f"{pkg}: {path.relative_to(ROOT)}")
    assert not offenders, "Active ghost references remain:\n" + "\n".join(sorted(set(offenders)))

def test_canonical_import_smoke():
    from crypto_trader.api.app import create_app  # noqa: F401
    from crypto_trader.llm_chief.engine import ChiefTraderEngine  # noqa: F401
    from crypto_trader.llm_chief.position_manager import LiveLLMPositionManager  # noqa: F401
    from crypto_trader.risk.engine import RiskEngine  # noqa: F401
    from crypto_trader.runtime.bootstrap import build_system  # noqa: F401
    from crypto_trader.runtime.engine import TradingEngine  # noqa: F401

def test_compile_active_source_tree():
    result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(ROOT / "src")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr

def test_full_portable_suite_after_quarantine():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests",
            "--ignore=tests/integration/test_legacy_quarantine_gate.py",
            "--ignore=tests/okx_credential/test_installer_diagnostics.py",
            "--deselect=tests/opportunity/test_full_market_factor_layer.py::test_factor_layer_never_imports_execution_surfaces",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        "Portable full-suite regression failed after quarantine.\n"
        + result.stdout[-12000:]
        + "\n"
        + result.stderr[-12000:]
    )
