"""Pure byte contract example; not a production schema or population proof.

shortcut: minimal synthetic field profile only; approve real historical schemas
and all caller adaptations before implementing a production loader.
"""

import json


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("non-finite JSON")


def classify(raw, *, io_error=None):
    if io_error is not None:
        return (
            "CHECKPOINT_MISSING"
            if isinstance(io_error, FileNotFoundError)
            else "CHECKPOINT_UNREADABLE"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject_constant
        )
    except (UnicodeDecodeError, ValueError):
        return "CHECKPOINT_CORRUPT"
    if not isinstance(value, dict):
        return "CHECKPOINT_SCHEMA_INVALID"
    if "schema_version" in value:
        if type(value["schema_version"]) is not int:
            return "CHECKPOINT_SCHEMA_INVALID"
        if value["schema_version"] != 1:
            return "CHECKPOINT_VERSION_UNSUPPORTED"
    expected = {"dataset": str, "symbol": str, "completed": bool, "retry_count": int}
    if any(type(value.get(key)) is not kind for key, kind in expected.items()):
        return "CHECKPOINT_SCHEMA_INVALID"
    return "CHECKPOINT_VALID"
