"""Canonical LLM policy + credential-source contract.

These lock down the two things that must never drift:

* the real trading decision (and every position HOLD/REDUCE/EXIT, which reuses
  the same call path) asks for ``deepseek-flash`` with thinking enabled at HIGH
  reasoning effort, while pure tool selection stays cheap;
* the credential comes from a FILE, lives in memory only, and a missing or
  unreadable file fails CLOSED instead of falling back to another model.
"""

from __future__ import annotations

import pytest

from crypto_trader.llm_chief.credentials import (
    ENV_KEY_FILE,
    ENV_KEY_LEGACY,
    ERROR_FILE_EMPTY,
    ERROR_UNCONFIGURED,
    SOURCE_ENV_LEGACY,
    SOURCE_EXPLICIT,
    SOURCE_FILE,
    Credential,
    load_credential,
)
from crypto_trader.llm_chief.policy import (
    CANONICAL_TRADING_MODEL,
    FORBIDDEN_MODELS,
    NO_FALLBACK_MODEL,
    OPERATION_GROWTH_REVIEW,
    OPERATION_POSITION_DECISION,
    OPERATION_TOOL_SELECTION,
    OPERATION_TRADING_DECISION,
    ForbiddenModelError,
    canonical_model,
    effective_policy,
    policy_for,
    reasoning_effort_for,
    thinking_for,
    validate_model,
)

# --------------------------------------------------------------- model policy


def test_default_model_is_deepseek_flash(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert canonical_model() == "deepseek-flash"
    assert CANONICAL_TRADING_MODEL == "deepseek-flash"


def test_trading_decision_uses_thinking_high():
    policy = policy_for(OPERATION_TRADING_DECISION)
    assert policy.thinking is True
    assert policy.reasoning_effort == "high"


def test_position_decision_uses_thinking_high():
    """HOLD/REDUCE/EXIT must not be cheaper than the entry decision."""
    policy = policy_for(OPERATION_POSITION_DECISION)
    assert policy.thinking is True
    assert policy.reasoning_effort == "high"


def test_growth_review_uses_thinking_high():
    policy = policy_for(OPERATION_GROWTH_REVIEW)
    assert policy.thinking is True
    assert policy.reasoning_effort == "high"


def test_tool_selection_may_disable_thinking():
    """Pure tool routing is explicitly allowed to skip hidden reasoning."""
    policy = policy_for(OPERATION_TOOL_SELECTION)
    assert policy.thinking is False
    assert policy.reasoning_effort == "low"
    # ...and the helper agrees with the richer accessor.
    assert thinking_for(OPERATION_TOOL_SELECTION) is False


def test_unknown_operation_opts_out_of_reasoning_by_default():
    """A brand-new operation must not inherit a trading-grade budget."""
    policy = policy_for("some_future_operation")
    assert policy.thinking is False
    assert policy.reasoning_effort == "low"


def test_trading_decision_is_not_hardcoded_low():
    """Guard the actual call site, not just the policy table."""
    import inspect

    from crypto_trader.llm_chief.engine import ChiefTraderEngine

    src = inspect.getsource(ChiefTraderEngine.decide)
    assert 'reasoning_effort="low"' not in src
    assert "reasoning_effort_for(OPERATION_TRADING_DECISION)" in src
    assert "OPERATION_TRADING_DECISION" in src


def test_tool_selection_call_site_uses_policy():
    import inspect

    from crypto_trader.llm_chief.engine import ChiefTraderEngine

    src = inspect.getsource(ChiefTraderEngine)
    assert "thinking_for(OPERATION_TOOL_SELECTION)" in src


@pytest.mark.parametrize("model", sorted(FORBIDDEN_MODELS))
def test_forbidden_models_fail_closed(model):
    with pytest.raises(ForbiddenModelError):
        validate_model(model)


def test_unknown_model_fails_closed():
    with pytest.raises(ForbiddenModelError):
        validate_model("gpt-4o")
    with pytest.raises(ForbiddenModelError):
        validate_model("deepseek-something-new")


def test_canonical_model_rejects_forbidden_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "deepseek-reasoner")
    with pytest.raises(ForbiddenModelError):
        canonical_model()


def test_canonical_model_accepts_canonical_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "deepseek-flash")
    assert canonical_model() == "deepseek-flash"


def test_no_model_fallback_is_declared():
    assert NO_FALLBACK_MODEL is True


def test_effective_policy_reports_required_runtime_facts(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    facts = effective_policy(OPERATION_TRADING_DECISION)
    assert facts["provider"] == "deepseek"
    assert facts["configured_model"] == "deepseek-flash"
    assert facts["effective_model"] == "deepseek-flash"
    assert facts["thinking"] is True
    assert facts["reasoning_effort"] == "high"
    # No credential material may ever appear here.
    assert "api_key" not in facts and "key" not in str(facts).lower()


# ------------------------------------------------------------------ credentials


def test_api_key_file_loads_in_memory(tmp_path):
    key_file = tmp_path / "deepseek.key"
    key_file.write_text("  sk-file-value-123\n")
    cred = load_credential(env={ENV_KEY_FILE: str(key_file)})
    assert cred.configured is True
    assert cred.api_key == "sk-file-value-123"  # whitespace stripped
    assert cred.source == SOURCE_FILE


def test_explicit_argument_wins(tmp_path):
    key_file = tmp_path / "deepseek.key"
    key_file.write_text("sk-from-file")
    cred = load_credential("sk-explicit", env={ENV_KEY_FILE: str(key_file)})
    assert cred.source == SOURCE_EXPLICIT
    assert cred.api_key == "sk-explicit"


def test_file_wins_over_legacy_env(tmp_path):
    key_file = tmp_path / "deepseek.key"
    key_file.write_text("sk-from-file")
    cred = load_credential(
        env={ENV_KEY_FILE: str(key_file), ENV_KEY_LEGACY: "sk-legacy"}
    )
    assert cred.source == SOURCE_FILE
    assert cred.api_key == "sk-from-file"


def test_legacy_env_is_marked_as_legacy():
    cred = load_credential(env={ENV_KEY_LEGACY: "sk-legacy"})
    assert cred.source == SOURCE_ENV_LEGACY
    assert cred.source == "env_legacy"


def test_missing_key_file_fails_closed(tmp_path):
    cred = load_credential(env={ENV_KEY_FILE: str(tmp_path / "nope.key")})
    assert cred.configured is False
    assert cred.api_key is None
    assert cred.source == SOURCE_FILE
    assert cred.error


def test_empty_key_file_fails_closed(tmp_path):
    key_file = tmp_path / "empty.key"
    key_file.write_text("   \n")
    cred = load_credential(env={ENV_KEY_FILE: str(key_file)})
    assert cred.configured is False
    assert cred.error == ERROR_FILE_EMPTY


def test_directory_as_key_file_fails_closed(tmp_path):
    cred = load_credential(env={ENV_KEY_FILE: str(tmp_path)})
    assert cred.configured is False


def test_broken_key_file_does_not_fall_back_to_legacy_env(tmp_path):
    """An operator who chose the file must not be silently served the env var."""
    cred = load_credential(
        env={ENV_KEY_FILE: str(tmp_path / "missing.key"), ENV_KEY_LEGACY: "sk-legacy"}
    )
    assert cred.configured is False
    assert cred.source == SOURCE_FILE


def test_no_credential_anywhere_fails_closed():
    cred = load_credential(env={})
    assert cred.configured is False
    assert cred.source == "none"
    assert cred.error == ERROR_UNCONFIGURED


def test_key_never_appears_in_repr_or_describe(tmp_path):
    secret = "sk-super-secret-value"
    key_file = tmp_path / "deepseek.key"
    key_file.write_text(secret)
    cred = load_credential(env={ENV_KEY_FILE: str(key_file)})
    assert secret not in repr(cred)
    assert secret not in str(cred.describe())
    assert "credential_source" in cred.describe()
    # The secret is still reachable programmatically (in memory only).
    assert cred.api_key == secret


def test_describe_reports_source_and_status_only():
    cred = Credential(api_key="sk-x", source=SOURCE_FILE)
    described = cred.describe()
    assert set(described) == {"credential_source", "configured", "error"}
    assert described["configured"] is True


def test_no_keychain_runtime_dependency():
    """The LLM credential path must not touch macOS Keychain at all.

    Scans EXECUTABLE code only (AST, docstrings stripped): the module's own
    docstring legitimately mentions that keychain is not used, and a raw text
    search would flag that explanation as a violation.
    """
    import ast
    import inspect

    from crypto_trader.llm_chief import credentials

    tree = ast.parse(inspect.getsource(credentials))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(
                getattr(body[0], "value", None), ast.Constant
            ):
                node.body = body[1:]
    code = ast.unparse(tree).lower()
    for forbidden in ("keychain", "find-generic", "subprocess", "os.system", "popen"):
        assert forbidden not in code, f"credential path references {forbidden!r}"


def test_provider_uses_canonical_credential_loader():
    import inspect

    from crypto_trader.llm_chief.provider import DeepSeekProvider

    src = inspect.getsource(DeepSeekProvider.__init__)
    assert "load_credential" in src
    assert "validate_model" in src or "canonical_model" in src


def test_provider_defaults_follow_policy():
    """complete_json must not hard-code a low default any more."""
    import inspect

    from crypto_trader.llm_chief.provider import DeepSeekProvider

    src = inspect.getsource(DeepSeekProvider.complete_json)
    assert "thinking_for(operation)" in src
    assert "reasoning_effort_for(operation)" in src


def test_reasoning_effort_helper_matches_policy():
    assert reasoning_effort_for(OPERATION_TRADING_DECISION) == "high"
    assert reasoning_effort_for(OPERATION_TOOL_SELECTION) == "low"


def test_key_never_appears_in_logs(tmp_path, caplog):
    """A resolved key must not reach any log record, at any level."""
    import logging

    secret = "sk-log-leak-canary-9f3a"
    key_file = tmp_path / "deepseek.key"
    key_file.write_text(secret)

    with caplog.at_level(logging.DEBUG):
        cred = load_credential(env={ENV_KEY_FILE: str(key_file)})
        # Touch the object the way a caller would.
        repr(cred), str(cred.describe()), cred.configured
        from crypto_trader.llm_chief.policy import effective_policy

        effective_policy(OPERATION_TRADING_DECISION)

    assert cred.api_key == secret  # resolved in memory
    captured = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in captured
    assert secret not in repr(cred)
    assert secret not in str(cred.describe())


def test_provider_diagnostics_never_expose_the_key(tmp_path):
    secret = "sk-diag-canary-1234"
    key_file = tmp_path / "deepseek.key"
    key_file.write_text(secret)
    from crypto_trader.llm_chief.provider import DeepSeekProvider

    provider = DeepSeekProvider(api_key=secret)
    blob = str(provider.diagnostics())
    assert secret not in blob
    assert provider.diagnostics()["credential_source"] == "explicit"
