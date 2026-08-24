from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    """Deterministic-format globally unique identifier: {prefix}_{uuid4hex}."""
    return f"{prefix}_{uuid.uuid4().hex}"


def is_valid_id(value: str, prefix: str | None = None) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if prefix is not None and not value.startswith(f"{prefix}_"):
        return False
    return True
