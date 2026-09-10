"""Research-only counterexample retention (no execution authority)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Counterexample:
    name: str
    evidence_present: bool
    outcome: str
    note: str


def retain_counterexample(
    name: str, *, evidence_present: bool, outcome: str, note: str
) -> Counterexample:
    return Counterexample(
        name=name,
        evidence_present=evidence_present,
        outcome=outcome,
        note=note,
    )
