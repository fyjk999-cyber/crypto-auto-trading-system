"""Low-Risk V2 provider durability regressions.

Covers the canonical Keychain startup path, deepseek-flash model policy,
fail-closed behavior without a credential, observable diagnostics and the
secret-free LaunchAgent contract.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from crypto_trader.api.deps import LLMRuntimeStatus
from crypto_trader.llm_chief.provider import DeepSeekProvider, resolve_trading_model
from crypto_trader.runtime.offline import OfflineMode

ROOT = Path(__file__).resolve().parents[2]
SECRET_MARKER = "sk-durability-test-secret-marker-do-not-log"


def _write_executable(path: Path, body: str) -> None:
    shebang = chr(35) + chr(33) + "/usr/bin/env bash\n"
    path.write_text(shebang + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _reduced_env(**extra: str) -> dict[str, str]:
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": os.environ.get("HOME", ""),
        "LOWRISK_SKIP_MIGRATIONS": "1",
        "PAPER_RUNTIME_PORT": "8010",
    }
    env.update(extra)
    return env


def test_generic_llm_model_cannot_override_trading_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("TRADING_LLM_MODEL", "deepseek-flash")
    assert resolve_trading_model() == "deepseek-flash"
    assert DeepSeekProvider(api_key="test").model == "deepseek-flash"
    monkeypatch.delenv("TRADING_LLM_MODEL")
    with pytest.raises(ValueError):
        resolve_trading_model()


async def test_missing_key_is_explicit_fail_closed_without_crashing(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("TRADING_LLM_MODEL", "deepseek-flash")
    status = LLMRuntimeStatus()
    await status.probe()  # must never raise
    snap = status.snapshot()
    assert snap["configured"] is False
    assert snap["reachable"] is False
    assert snap["provider_state"] == "PROVIDER_UNCONFIGURED"
    assert snap["configured_provider"] == "none"
    assert snap["configured_model"] is None
    assert snap["last_error"] == "NOT_CONFIGURED"


async def test_unconfigured_provider_keeps_new_risk_blocked(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    status = LLMRuntimeStatus()
    await status.probe()
    mode = OfflineMode()
    assert mode.allows_new_risk() is True
    mode.enter(status.snapshot()["provider_state"], now=datetime(2026, 9, 16, tzinfo=UTC))
    assert mode.allows_new_risk() is False
    assert mode.blocks_new_risk({"lifecycle_action": "ADD"}, "live_llm") is True
    assert mode.blocks_new_risk({"reduce_only": True}, "live_llm_position") is False


async def test_real_probe_contract_and_effective_diagnostics(monkeypatch):
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"runtime_health":"ok"}'}}]}
        )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("TRADING_LLM_MODEL", "deepseek-flash")
    provider = DeepSeekProvider(
        api_key="test-secret", transport=httpx.MockTransport(handler)
    )
    status = LLMRuntimeStatus(provider_instance=provider)
    await status.probe()
    payload = captured["payload"]
    assert payload["model"] == "deepseek-flash"
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"
    snap = status.snapshot()
    assert snap["reachable"] is True
    assert snap["provider_state"] == "PROVIDER_CONFIGURED"
    assert snap["configured_provider"] == "deepseek"
    assert snap["configured_model"] == "deepseek-flash"
    assert snap["effective_provider"] == "deepseek"
    assert snap["effective_model"] == "deepseek-flash"
    assert snap["last_success_ts"] is not None
    assert snap["last_error"] is None


async def test_probe_exception_is_observed_without_crashing(monkeypatch):
    class ExplodingProvider:
        def healthy(self) -> bool:
            return True

        async def complete_json(self, **kwargs):
            raise RuntimeError("transport exploded")

        def diagnostics(self) -> dict:
            return {}

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("TRADING_LLM_MODEL", "deepseek-flash")
    status = LLMRuntimeStatus(provider_instance=ExplodingProvider())
    await status.probe()
    snap = status.snapshot()
    assert snap["reachable"] is False
    assert snap["provider_state"] == "PROVIDER_UNREACHABLE"
    assert snap["last_error"] == "PROBE_EXCEPTION:RuntimeError"


def _fake_runtime_script() -> str:
    return (
        'if [ -n "${DEEPSEEK_API_KEY:-}" ]; then key_present=true; '
        "else key_present=false; fi\n"
        "printf '{"
        '\\"key_present\\": %s, \\"provider\\": \\"%s\\", '
        '\\"model\\": \\"%s\\", \\"llm_model\\": \\"%s\\", '
        '\\"live\\": \\"%s\\", \\"port\\": \\"%s\\"'
        "}\\n' \\\n"
        '  "$key_present" "${LLM_PROVIDER:-}" '
        '"${TRADING_LLM_MODEL:-}" \\\n'
        '  "${LLM_MODEL:-unset}" "${LIVE_TRADING_ENABLED:-}" '
        '"${PAPER_RUNTIME_PORT:-}"\n'
    )


def _run_wrapper(tmp_path: Path, *, key_available: bool) -> subprocess.CompletedProcess:
    keychain = tmp_path / "fake-keychain.sh"
    runtime = tmp_path / "fake-runtime.sh"
    if key_available:
        _write_executable(keychain, "printf '%s' '" + SECRET_MARKER + "'\n")
    else:
        _write_executable(keychain, "exit 1\n")
    _write_executable(runtime, _fake_runtime_script())
    return subprocess.run(
        [str(ROOT / "scripts/run_low_risk_paper_secure.sh")],
        env=_reduced_env(
            LOWRISK_KEYCHAIN_SWIFT=str(keychain), LOWRISK_PYTHON=str(runtime)
        ),
        capture_output=True,
        text=True,
        check=False,
    )


def test_secure_wrapper_injects_keychain_without_logging_secret(tmp_path):
    first = _run_wrapper(tmp_path, key_available=True)
    assert first.returncode == 0, first.stderr
    payload = json.loads(first.stdout.strip().splitlines()[-1])
    assert payload["key_present"] is True
    assert payload["provider"] == "deepseek"
    assert payload["model"] == "deepseek-flash"
    assert payload["llm_model"] == "unset"
    assert payload["live"] == "false"
    assert payload["port"] == "8010"
    assert SECRET_MARKER not in first.stdout
    assert SECRET_MARKER not in first.stderr

    # Restart path: a fresh wrapper process re-injects the same Keychain credential.
    second = _run_wrapper(tmp_path, key_available=True)
    assert second.returncode == 0, second.stderr
    second_payload = json.loads(second.stdout.strip().splitlines()[-1])
    assert second_payload["key_present"] is True
    assert SECRET_MARKER not in second.stdout + second.stderr


def test_secure_wrapper_missing_key_is_fail_closed_and_observable(tmp_path):
    result = _run_wrapper(tmp_path, key_available=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["key_present"] is False
    assert payload["provider"] == "deepseek"
    assert payload["model"] == "deepseek-flash"
    assert payload["live"] == "false"
    assert "LLM_PROVIDER_STATE=PROVIDER_UNCONFIGURED" in result.stderr
    assert "PROVIDER_UNCONFIGURED" in result.stderr


def test_all_startup_paths_converge_on_one_secure_wrapper():
    keychain = (ROOT / "scripts/deepseek-keychain.sh").read_text()
    start_paper = (ROOT / "scripts/start-paper.sh").read_text()
    fund_manager = (ROOT / "scripts/start-ai-fund-manager.sh").read_text()
    wrapper = (ROOT / "scripts/run_low_risk_paper_secure.sh").read_text()
    assert "deepseek-v4-pro" not in keychain
    assert "run_low_risk_paper_secure.sh" in keychain
    assert "run_low_risk_paper_secure.sh" in start_paper
    assert "run_low_risk_paper_secure.sh" in fund_manager
    assert "crypto_trader.runtime.local_runner" in fund_manager
    for text in (wrapper, keychain, start_paper, fund_manager):
        assert "set -x" not in text
    assert "TRADING_LLM_MODEL=deepseek-flash" in wrapper
    assert "export LLM_MODEL=" not in wrapper
    assert "unset LLM_MODEL" in wrapper
    assert "RUNNING_SHA" in wrapper
    assert "DATABASE_URL" in (ROOT / "migrations/env.py").read_text()


def test_launch_agent_contract_is_secret_free_and_durable():
    template = (ROOT / "deploy/launchd/com.lowrisk.paper.plist.template").read_text()
    installer = (ROOT / "scripts/install_low_risk_paper_launchagent.sh").read_text()
    assert "<key>Label</key>" in template
    assert "com.lowrisk.paper" in template
    assert "<key>RunAtLoad</key>" in template
    assert "<key>KeepAlive</key>" in template
    assert "<key>ThrottleInterval</key>" in template
    assert "<integer>15</integer>" in template
    assert "8010" in template
    assert "DEEPSEEK" not in template
    assert "run_low_risk_paper_secure.sh" in template
    assert "plutil -lint" in installer
    assert "launchctl bootstrap" in installer
    assert "DEEPSEEK" not in installer
