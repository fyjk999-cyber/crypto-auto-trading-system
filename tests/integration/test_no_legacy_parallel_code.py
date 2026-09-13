from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DELETED_LEGACY_PACKAGES = [
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
    "vector_memory",
]

DELETED_FILES = [
    "src/crypto_trader/runtime/ai_position_bridge.py",
    "scripts/performance_smoke.py",
]

ROOT = Path(__file__).resolve().parents[2]


def _active_files():
    roots = [ROOT / "src", ROOT / "tests", ROOT / "scripts", ROOT / "deploy", ROOT / ".github"]
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".sh", ".toml", ".yml", ".yaml"}:
                yield path
    for name in ("pyproject.toml", "Dockerfile"):
        path = ROOT / name
        if path.exists():
            yield path


def test_deleted_parallel_paths_stay_deleted():
    missing = []
    for pkg in DELETED_LEGACY_PACKAGES:
        path = ROOT / "src" / "crypto_trader" / pkg
        if path.exists():
            missing.append(str(path.relative_to(ROOT)))
    for relative in DELETED_FILES:
        path = ROOT / relative
        if path.exists():
            missing.append(relative)
    assert not missing, "Deleted legacy paths were reintroduced:\n" + "\n".join(sorted(missing))


def test_no_active_ghost_references_to_deleted_parallel_packages():
    offenders = []
    patterns = {
        pkg: re.compile(r"crypto_trader\." + re.escape(pkg) + r"(?:\.|\b)")
        for pkg in DELETED_LEGACY_PACKAGES
    }
    patterns["runtime_ai_position_bridge"] = re.compile(
        r"crypto_trader\.runtime\.ai_position_bridge(?:\.|\b)"
    )
    for path in _active_files():
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pkg, pattern in patterns.items():
            if pattern.search(text):
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
