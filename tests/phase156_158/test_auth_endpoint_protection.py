from crypto_trader.security import auth as auth_mod
from crypto_trader.security.auth import Role, require_role_dependency


def test_auth_disabled_allows_internal_calls():
    dep = require_role_dependency(Role.ADMIN)
    ctx = dep(authorization=None)
    assert ctx.role == "ADMIN"


def test_auth_enabled_denies_missing_token(monkeypatch):
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth_mod,
        "ROLE_KEYS",
        {Role.ADMIN: "secret-admin", Role.OPERATOR: "secret-op", Role.VIEWER: "secret-viewer"},
    )
    dep = require_role_dependency(Role.ADMIN)
    try:
        dep(authorization=None)
        raise AssertionError()
    except PermissionError as exc:
        assert "AUTH" in str(exc)


def test_auth_enabled_denies_wrong_role(monkeypatch):
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth_mod,
        "ROLE_KEYS",
        {Role.ADMIN: "secret-admin", Role.OPERATOR: "secret-op", Role.VIEWER: "secret-viewer"},
    )
    dep = require_role_dependency(Role.ADMIN)
    try:
        dep(authorization="Bearer secret-op")
        raise AssertionError()
    except PermissionError:
        pass


def test_audit_record_shape():
    from crypto_trader.security.auth import record_audit

    event = record_audit("admin", "ADMIN", "kill_switch", "global", "test", "OK")
    assert event["actor"] == "admin"
    assert event["action"] == "kill_switch"
    assert "timestamp" in event
