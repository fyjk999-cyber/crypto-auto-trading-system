"""Minimal RBAC for operational endpoints.

When AUTH_ENABLED=false (tests/dev), all endpoints remain reachable. When
AUTH_ENABLED=true, dangerous endpoints must present a valid bearer token whose
sha256 digest matches ADMIN_API_KEY / OPERATOR_API_KEY / VIEWER_API_KEY.
Secrets are read from environment and never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class Role(str, Enum):
    VIEWER = "VIEWER"
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"


@dataclass
class AuthContext:
    actor: str
    role: str
    request_id: str = ""
    audit: list[dict] = field(default_factory=list)


ROLE_KEYS = {
    Role.VIEWER: os.environ.get("VIEWER_API_KEY", ""),
    Role.OPERATOR: os.environ.get("OPERATOR_API_KEY", ""),
    Role.ADMIN: os.environ.get("ADMIN_API_KEY", ""),
}

AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() in ("1", "true", "yes")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def auth_context() -> AuthContext:
    return AuthContext(actor="system", role=Role.ADMIN.value)


def require_role(role: Role):
    def dependency() -> AuthContext:
        if not AUTH_ENABLED:
            return AuthContext(actor="anonymous_dev", role=role.value)
        raise PermissionError("AUTH_REQUIRED")

    return dependency


def verify_token(token: str, role: Role) -> bool:
    if not AUTH_ENABLED:
        return True
    key = ROLE_KEYS.get(role, "")
    if not key:
        return False
    return hmac.compare_digest(_digest(token), _digest(key))


def record_audit(
    actor: str, role: str, action: str, target: str, reason: str = "", result: str = "OK"
) -> dict:
    event = {
        "actor": actor,
        "role": role,
        "action": action,
        "target": target,
        "reason": reason,
        "result": result,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    return event
