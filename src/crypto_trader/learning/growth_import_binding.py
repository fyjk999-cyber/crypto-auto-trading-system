"""Explicit read-only target binding for any legacy Growth import attempt.

The final Low-Risk V2 runtime does not import legacy Growth databases. Any
future operator-run import must first bind the exact source and target files;
the binding fails closed if the target confirmation hash does not match, if the
paths are identical, or if either file is missing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


class ImportBindingError(RuntimeError):
    """Raised when an import source/target binding is not safe."""


@dataclass(frozen=True)
class ImportTargetBinding:
    source_path: str
    target_path: str
    target_sha256: str
    source_size: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def target_fingerprint(path: str) -> str:
    return _sha256_file(Path(path))


def bind_import_target(
    source_path: str,
    target_path: str,
    *,
    confirm_target_fingerprint: str,
) -> ImportTargetBinding:
    source = Path(source_path).resolve()
    target = Path(target_path).resolve()
    if source == target:
        raise ImportBindingError("SOURCE_TARGET_IDENTICAL")
    if not source.is_file():
        raise ImportBindingError("SOURCE_MISSING")
    if not target.is_file():
        raise ImportBindingError("TARGET_MISSING")
    fingerprint = _sha256_file(target)
    if confirm_target_fingerprint != fingerprint:
        raise ImportBindingError("TARGET_CONFIRMATION_MISMATCH")
    return ImportTargetBinding(
        source_path=str(source),
        target_path=str(target),
        target_sha256=fingerprint,
        source_size=source.stat().st_size,
    )
