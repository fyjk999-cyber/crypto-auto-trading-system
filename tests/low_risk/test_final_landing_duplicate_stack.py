"""PR #5 guard: one canonical runtime entry, no legacy parallel stack wiring."""

from __future__ import annotations

import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "src" / "crypto_trader" / "runtime"


def test_exactly_one_canonical_runtime_bootstrap() -> None:
    hits = [
        path.name
        for path in sorted(RUNTIME.glob("*.py"))
        if "async def build_system(" in path.read_text(encoding="utf-8")
    ]
    assert hits == ["bootstrap.py"]


def test_legacy_ai_position_bridge_is_not_wired_into_bootstrap() -> None:
    source = (RUNTIME / "bootstrap.py").read_text(encoding="utf-8")
    assert "AIPositionRuntimeBridge" not in source
    bootstrap = importlib.import_module("crypto_trader.runtime.bootstrap")
    assert not hasattr(bootstrap, "AIPositionRuntimeBridge")


def test_runtime_stack_does_not_import_legacy_ai_brain() -> None:
    for path in sorted(RUNTIME.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if path.name == "ai_position_bridge.py":
            continue  # isolated legacy adapter, guarded by not being wired
        assert "crypto_trader.ai_brain" not in text


def test_only_one_local_runner_entrypoint() -> None:
    hits = [
        path.name
        for path in sorted((ROOT / "src" / "crypto_trader" / "runtime").glob("*.py"))
        if "uvicorn.Config(" in path.read_text(encoding="utf-8")
    ]
    assert hits == ["local_runner.py"]
