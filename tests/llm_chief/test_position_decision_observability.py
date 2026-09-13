"""P0-4: a position decision must be explicable from the AUDIT ALONE.

A FAIL_CLOSED whose cause is only discoverable by joining ``llm_decisions``
leaves an unmanaged position impossible to explain at the point an operator
actually looks. That is not hypothetical: an IOST position sat unmanaged through
repeated ``FAIL_CLOSED`` because the audit payload carried only
action/symbol/trade_plan_id/decision_authority, and the reason lived in another
table.

The invariant pinned here: whatever the Chief decided, the audit payload and the
persisted decision agree on the reason codes, provider and model.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from crypto_trader.llm_chief.decision import ChiefTraderDecision, PositionState
from crypto_trader.observability.audit import AuditService
from crypto_trader.persistence.models import LLMDecisionORM
from tests.llm_chief.test_position_manager import (
    active_plan,
    context,
)
from tests.llm_chief.test_position_manager import (
    manager as _manager_fixture,
)


class FailingChief:
    """Returns FAIL_CLOSED exactly as a provider outage does."""

    def __init__(self, reason_codes, *, provider="deepseek", model="deepseek-flash"):
        self.reason_codes = reason_codes
        self.provider = provider
        self.model = model

    async def decide(self, ctx):
        return ChiefTraderDecision(
            decision_id="pos-fail-closed",
            symbol=ctx.symbol,
            position_state=PositionState.OPEN,
            action="FAIL_CLOSED",
            market_regime=ctx.regime,
            thesis="provider unavailable",
            position_size_request=0.0,
            reason_codes=list(self.reason_codes),
            model_provider=self.provider,
            model=self.model,
        )


async def _run(database, chief):
    """Plan is resolved by SYMBOL inside review(); no plan argument is passed."""
    plan = await active_plan(database, "LONG")
    ctx, position = context("0.5")
    mgr = _manager_fixture(database, chief)
    await mgr.review(ctx, position)
    return plan


@pytest.mark.asyncio
async def test_fail_closed_reason_codes_are_visible_in_the_audit(database):
    chief = FailingChief(["NO_API_KEY"])
    plan = await _run(database, chief)

    audit = AuditService(database.session_factory)
    rows = [
        row
        for row in await audit.list_recent(limit=50)
        if row.action == "LIVE_LLM_POSITION_DECISION"
    ]
    assert rows, "no position decision was audited"
    payload = rows[0].after_json or {}

    # The whole point: an operator reading ONLY the audit must know WHY.
    assert payload.get("reason_codes") == ["NO_API_KEY"], (
        f"the audit must expose the reason codes, got {payload.get('reason_codes')!r}"
    )
    assert payload.get("model_provider") == "deepseek"
    assert payload.get("model") == "deepseek-flash"
    assert payload.get("action") == "FAIL_CLOSED"
    assert payload.get("trade_plan_id") == plan.trade_plan_id
    assert "decision_authority" in payload


@pytest.mark.asyncio
async def test_audit_reason_codes_match_the_persisted_decision(database):
    """The two sources must not disagree - that is what makes the audit trustworthy."""
    chief = FailingChief(["NO_API_KEY"], provider="deepseek", model="deepseek-flash")
    await _run(database, chief)

    async with database.session_factory() as session:
        persisted = (
            await session.execute(
                select(LLMDecisionORM).order_by(LLMDecisionORM.created_at.desc())
            )
        ).scalars().first()
    assert persisted is not None, "the decision was not persisted"
    assert persisted.action == "FAIL_CLOSED"

    audit = AuditService(database.session_factory)
    rows = [
        row
        for row in await audit.list_recent(limit=50)
        if row.action == "LIVE_LLM_POSITION_DECISION"
        and (row.after_json or {}).get("action") == "FAIL_CLOSED"
    ]
    assert rows, "no FAIL_CLOSED position decision was audited"
    payload = rows[0].after_json or {}

    assert payload["reason_codes"] == list(persisted.reason_codes_json or []), (
        "audit reason codes disagree with the persisted decision"
    )
    assert payload["model_provider"] == persisted.model_provider
    assert payload["model"] == persisted.model


@pytest.mark.asyncio
async def test_absent_reason_codes_audit_as_an_empty_list(database):
    """A decision without reason codes must audit as [] rather than null."""
    chief = FailingChief([])
    await _run(database, chief)

    audit = AuditService(database.session_factory)
    rows = [
        row
        for row in await audit.list_recent(limit=50)
        if row.action == "LIVE_LLM_POSITION_DECISION"
    ]
    assert rows
    payload = rows[0].after_json or {}
    assert payload.get("reason_codes") == [], (
        "an empty reason-code set must audit as [] so the field is always present"
    )
