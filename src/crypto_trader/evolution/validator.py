"""Proposal validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValidationResult:
    passed: bool
    reason: str


def validate_proposal(proposal) -> ValidationResult:
    if not proposal.parameter_changes:
        return ValidationResult(False, "NO_PARAMETER_CHANGES")
    if proposal.status != "PROPOSED":
        return ValidationResult(False, "INVALID_STATUS")
    return ValidationResult(True, "OK")
