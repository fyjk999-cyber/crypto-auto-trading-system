"""Post-submit order state sync must tolerate inline event-stream races."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from crypto_trader.domain.enums import OrderStatus
from crypto_trader.domain.errors import InvalidStateTransition
from tests.conftest import make_paper_engine


@pytest.mark.parametrize(
    "failure",
    [
        InvalidStateTransition("duplicate ack"),
        IntegrityError("update", {}, Exception("duplicate event")),
    ],
)
async def test_post_submit_sync_skips_duplicate_transition(database, failure):
    engine = make_paper_engine(database)
    order = SimpleNamespace(internal_order_id="ord-sync", symbol="BTCUSDT")
    exchange_order = SimpleNamespace(
        exchange_order_id="exch-sync",
        status=OrderStatus.OPEN,
        rejection_reason=None,
    )

    async def duplicate_ack(*args, **kwargs):
        raise failure

    engine.order_manager.ack = duplicate_ack
    audit_events = []

    async def audit(event, **kwargs):
        audit_events.append((event, kwargs))

    engine.audit.log = audit
    # Must not raise; the event stream owns the transition.
    await engine._sync_submitted_order_state(
        order,
        exchange_order,
        client_order_id="cid-sync",
        run_id="run-sync",
    )
    assert audit_events
    assert audit_events[0][0] == "ORDER_STATE_SYNC_SKIPPED"
    assert audit_events[0][1]["order_id"] == "ord-sync"
    assert audit_events[0][1]["after"]["exchange_status"] == "OPEN"
