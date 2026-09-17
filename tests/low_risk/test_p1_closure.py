"""P1 closure regressions: startup classification, model policy, promotion semantics."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_startup_path_classification_labels() -> None:
    expected = {
        "scripts/run_low_risk_paper_secure.sh": "CANONICAL_RUNTIME_ENTRY",
        "scripts/deepseek-keychain.sh": "MANUAL_WRAPPER_ONLY",
        "scripts/start-paper.sh": "MANUAL_WRAPPER_ONLY",
        "scripts/start-ai-fund-manager.sh": "MANUAL_WRAPPER_ONLY",
        "scripts/start-local-system.sh": "DEV_UI_ONLY",
    }
    for relative, label in expected.items():
        assert label in (ROOT / relative).read_text()
    dev_ui = (ROOT / "scripts/start-local-system.sh").read_text()
    assert "NOT_RUNTIME_OWNER" in dev_ui
    for line in dev_ui.splitlines():
        stripped = line.strip()
        assert not (
            stripped.startswith(("exec ", "nohup "))
            and "crypto_trader.runtime.local_runner" in stripped
        ), line


def test_production_paths_contain_only_policy_deny_list_references() -> None:
    banned = ("deepseek-v4-pro", "deepseek-flash-high")
    for root in ("src", "scripts", "deploy"):
        for path in (ROOT / root).rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".sh", ".md", ".json"}:
                continue
            for number, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                for token in banned:
                    if token in line:
                        assert "FORBIDDEN_PRODUCTION_MODELS" in line, (path, number, line)
    env_example = (ROOT / ".env.example").read_text()
    assert "TRADING_LLM_MODEL=deepseek-flash" in env_example
    for token in banned:
        assert token not in env_example


def test_promotion_status_does_not_imply_an_eligible_challenger() -> None:
    receipt = (ROOT / "docs/low-risk/receipts/P1_CLOSURE_RECEIPT.md").read_text()
    assert "PROMOTION_POLICY = EVIDENCE_GATED" in receipt
    assert "PROMOTION_PIPELINE_AVAILABLE = YES" in receipt
    assert "CURRENT_ELIGIBLE_CHALLENGER = NO" in receipt
    assert "REAL_PROMOTION_GATE" in receipt
    assert "GATE = OPEN" not in receipt
