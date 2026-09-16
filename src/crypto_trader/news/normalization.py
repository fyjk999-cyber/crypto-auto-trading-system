"""Normalization and sanitization for untrusted external News text.

Raw provider truth is never mutated by this module. These helpers produce
derived comparison/safe-text forms only and are explicitly time-invariant.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SCRIPT_RE = re.compile(r"<(script|style|iframe|object|embed)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_TRACKING_PREFIXES = ("utm_", "gclid", "fbclid", "mc_", "ref", "source", "cmp")
_NON_WORD_RE = re.compile(r"[^a-z0-9$#%]+")


def sanitize_external_text(text: str | None, *, max_len: int = 8000) -> str:
    """Turn untrusted markup into bounded plain quoted evidence text.

    The function removes executable markup and control characters but does not
    drop instruction-like words: those remain literal evidence content and can
    never become instructions because callers quote the result as data.
    """
    if not text:
        return ""
    value = str(text)
    value = _SCRIPT_RE.sub(" ", value)
    value = _TAG_RE.sub(" ", value)
    value = html.unescape(value)
    value = _CONTROL_RE.sub(" ", value)
    value = value.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value[:max_len]


def normalize_for_compare(text: str | None) -> str:
    if not text:
        return ""
    value = unicodedata.normalize("NFKC", str(text)).lower()
    value = html.unescape(value)
    value = _TAG_RE.sub(" ", value)
    value = _NON_WORD_RE.sub(" ", value)
    return _WHITESPACE_RE.sub(" ", value).strip()


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(str(url).strip())
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PREFIXES)
    ]
    normalized_query = urlencode(query_pairs)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, normalized_query, ""))


def hash_text(text: str) -> str:
    return hashlib.sha256(normalize_for_compare(text).encode("utf-8")).hexdigest()


def source_payload_hash(*parts: str | None) -> str:
    payload = "\u241f".join(str(part or "") for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def token_set(text: str) -> set[str]:
    return {token for token in normalize_for_compare(text).split() if len(token) > 2}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def title_similarity(left: str | None, right: str | None) -> float:
    a = normalize_for_compare(left)
    b = normalize_for_compare(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def text_similarity(left: str | None, right: str | None) -> float:
    a_tokens = token_set(left or "")
    b_tokens = token_set(right or "")
    lexical = jaccard(a_tokens, b_tokens)
    sequence = SequenceMatcher(
        None, normalize_for_compare(left or ""), normalize_for_compare(right or "")
    ).ratio()
    return max(lexical, sequence)


def contains_source_attribution(text: str | None, other_source_domain: str | None) -> bool:
    if not text or not other_source_domain:
        return False
    domain = other_source_domain.lower().split(".")[0]
    if len(domain) < 3:
        return False
    return domain in normalize_for_compare(text)
