"""Bounded, content-free diagnostics. Never a parser or trading authority."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime

_LOGGER = logging.getLogger(__name__)


def _opaque_id(value):
    return value if isinstance(value, str) and re.fullmatch(r"[\w-]{1,128}", value) else None


def response_metadata(
    *, provider, model, content, payload, http_status, request_id, attempt, max_attempts, max_tokens
):
    """Whitelist only factual wire metadata; never retain input/prefix/suffix."""
    choice = payload.get("choices", [{}])[0]
    reason = choice.get("finish_reason")
    reason = (
        reason
        if isinstance(reason, str) and reason in {"stop", "length", "content_filter", "tool_calls"}
        else None
    )
    usage = payload.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("completion_tokens_details")
    details = details if isinstance(details, dict) else {}
    try:
        raw_bytes = content.encode("utf-8")
    except UnicodeEncodeError:
        raw_bytes = None  # No invented byte/hash evidence for invalid Unicode.
    stripped = content.strip()
    first = "NONE" if not stripped else {"{": "OBJECT", "[": "ARRAY"}.get(stripped[0], "OTHER")
    last = (
        "NONE" if not stripped else {"}": "OBJECT_END", "]": "ARRAY_END"}.get(stripped[-1], "OTHER")
    )
    out = {
        "collected_at": datetime.now(UTC).isoformat(),
        "provider": provider,
        "model": model,
        "http_status": http_status,
        "provider_request_id": _opaque_id(request_id),
        "response_id": _opaque_id(payload.get("id")),
        "attempt_number": attempt,
        "max_attempts": max_attempts,
        "configured_max_output_tokens": max_tokens,
        "finish_reason": reason,
        "response_character_length": len(content),
        "response_byte_length": len(raw_bytes) if raw_bytes is not None else None,
        "response_sha256": hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else None,
        "response_empty": not stripped,
        "leading_non_ws_token_class": first,
        "trailing_non_ws_token_class": last,
        "markdown_fence_detected": stripped.startswith("```"),
        "ends_with_json_terminator": last in {"OBJECT_END", "ARRAY_END"},
    }
    for key, value in {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
    }.items():
        out[key] = value if type(value) is int and value >= 0 else None
    return out


def decoding_failure(metadata, error):
    out = dict(metadata)
    out.update(
        json_parse_ok=False,
        schema_validation_ok=None,
        json_error_message=error.msg,
        json_error_pos=error.pos,
        json_error_lineno=error.lineno,
        json_error_colno=error.colno,
    )
    out["classification"] = (
        "PROVIDER_REPORTED_TRUNCATION"
        if out["finish_reason"] == "length"
        else "EMPTY_RESPONSE"
        if out["response_empty"]
        else "MARKDOWN_WRAPPED"
        if out["markdown_fence_detected"]
        else "JSON_DECODE_ERROR"
    )
    return out


def validation_failure(metadata, error, allowed_fields):
    out = dict(metadata)
    # Pydantic error messages/context/input can contain the response or secrets.
    # Keep only library error codes and known schema field names/numeric indices.
    errors = (
        error.errors(include_input=False, include_context=False, include_url=False)
        if hasattr(error, "errors")
        else []
    )
    out.update(
        json_parse_ok=True,
        schema_validation_ok=False,
        classification="SCHEMA_VALIDATION_ERROR",
        validation_errors=[
            {
                "validation_error_code": e["type"],
                "validation_path": [
                    v if type(v) is int or v in allowed_fields else "<unknown-field>"
                    for v in e.get("loc", ())
                ],
            }
            for e in errors[:16]
        ],
    )
    if not errors:
        out["validation_errors"] = [
            {"validation_error_code": type(error).__name__, "validation_path": []}
        ]
    return out


def publish_failure(metadata, **binding):
    """Existing application logs persist JSON, no DB migration/new file writer.

    Diagnostic-handler failures must not affect retry/offline/trading behavior.
    """
    try:
        _LOGGER.warning(
            "LLM_FAILURE_METADATA %s", json.dumps({**metadata, **binding}, sort_keys=True)
        )
    except Exception:
        pass
