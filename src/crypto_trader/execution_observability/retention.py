"""Retention policy for execution evidence (Phase E0, section 23).

Orderbook evidence grows fast - a full book is captured at seven offsets for
every ENTRY. Storing every second of every symbol forever is not the goal, and
the directive is explicit that event-scoped evidence is preferred over
"store everything forever".

The policy here is deliberately conservative and OBSERVATION-FREE: it computes
what WOULD be pruned and never deletes anything on its own. Deleting historical
market facts is irreversible, so the decision belongs to an explicit, separate
action rather than to a background job that starts running by itself.

What is retained unconditionally:
  * ``entry_execution_evidence`` - one row per ENTRY. Tiny, and the anchor that
    makes everything else interpretable.
  * The T+0 sample of every entry - the pre-submit to first-observation link.
  * Any entry whose outcome is still unresolved.

What is a candidate for pruning once it is old:
  * The dense intermediate offsets (T+1, T+2, T+5) of entries older than the
    retention window. These are the bulk of the volume and the least
    informative once an entry is closed and its outcome is known.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Offsets that are cheap to lose once an entry is closed and settled.
DENSE_OFFSETS: tuple[int, ...] = (1, 2, 5)

#: Offsets kept for every entry regardless of age - the sparse, informative ones.
ANCHOR_OFFSETS: tuple[int, ...] = (0, 15, 30, 60)

DEFAULT_RETENTION_DAYS = 90


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    """What a prune WOULD remove. Nothing here executes a delete."""

    retention_days: int
    dense_offsets: tuple[int, ...]
    anchor_offsets: tuple[int, ...]
    rationale: str

    def as_dict(self) -> dict:
        return {
            "retention_days": self.retention_days,
            "dense_offsets": list(self.dense_offsets),
            "anchor_offsets": list(self.anchor_offsets),
            "deletes_anything": False,
            "rationale": self.rationale,
        }


def default_retention_plan(days: int = DEFAULT_RETENTION_DAYS) -> RetentionPlan:
    return RetentionPlan(
        retention_days=days,
        dense_offsets=DENSE_OFFSETS,
        anchor_offsets=ANCHOR_OFFSETS,
        rationale=(
            "Keep every entry evidence row and the sparse anchor samples "
            "(T+0/15/30/60) indefinitely; only the dense intermediate offsets "
            "(T+1/2/5) of entries older than the window are prune candidates. "
            "This module computes the plan but never deletes: removing historical "
            "market facts is irreversible and requires an explicit operator action."
        ),
    )


def prunable_sample_predicate_sql(retention_days: int = DEFAULT_RETENTION_DAYS) -> str:
    """SQL for the prune CANDIDATE set. Returned as text so it is auditable and
    can be reviewed before anyone runs it - this function does not execute it."""
    offsets = ", ".join(str(o) for o in DENSE_OFFSETS)
    return (
        "SELECT s.sample_id FROM entry_orderbook_samples s "
        "JOIN entry_execution_evidence e ON e.evidence_id = s.evidence_id "
        f"WHERE s.offset_seconds IN ({offsets}) "
        f"AND e.created_at < datetime('now', '-{int(retention_days)} days')"
    )
