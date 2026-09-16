"""Factual position/plan state version shared by runtime and position manager.

Any material factual change (fill, partial reduction, plan version, leg
quantity) must change this value so stale LLM decisions can be rejected.
"""

from __future__ import annotations


def position_state_version(position, plan) -> str:
    updated = getattr(position, "updated_at", None)
    return "|".join(
        [
            str(plan.trade_plan_id),
            str(getattr(plan, "plan_version", 1)),
            str(position.quantity),
            updated.isoformat() if updated is not None else "none",
        ]
    )
