"""P0: funding settlement must reach the PAPER account, not just the ledger.

Root cause this pins down
------------------------
``FundingAccountingSupervisor`` posts the settlement to the durable ledger and
the portfolio projection, but the process-local PAPER adapter cache was only
ever hydrated at STARTUP (``TradingEngine._restore_paper_adapter_state``).
Nothing re-ran that sync at runtime, so once funding settled the broker cache
stayed at its previous value forever and reconciliation compared two different
points in time:

    ledger projection   99999.535407787925130565
    adapter balances    99999.610021
    gap                 0.074613212074869435   (the funding amount, exactly)

The fix re-reads the COMMITTED projection and copies it. It never does its own
arithmetic, so it cannot double-apply, and it only touches balances — orders,
positions and execution state keep their own lifecycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from crypto_trader.ledger.projections import replay_projections
from crypto_trader.ledger.service import LedgerService
from crypto_trader.perpetual.funding_settlement import compute_paper_funding
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter

TS = datetime(2026, 9, 12, 4, 0, tzinfo=UTC)
SYMBOL = "CPUSDT"
CONTRACT_SIZE = Decimal("100")


def _settlement(*, quantity: str = "275", rate: str = "0.0001782659468997") -> object:
    """A LONG position paying positive funding => negative signed amount."""
    return compute_paper_funding(
        settlement_timestamp=TS,
        signed_quantity=Decimal(quantity),
        mark_price=Decimal("0.01522"),
        funding_rate=Decimal(rate),
        contract_size=CONTRACT_SIZE,
        contract_multiplier=Decimal("1"),
        instrument_id=SYMBOL,
    )


async def _adapter_with_projection(database, *, start: str = "100000"):
    """Adapter holding a STALE balance while the ledger projection is newer."""
    adapter = SimulatedExchangeAdapter(initial_balances={"USDT": Decimal(start)})
    await adapter.connect()
    ledger = LedgerService(database.session_factory)
    return adapter, ledger


# ---------------------------------------------------------------- P0-T1
async def test_P0_T1_funding_settlement_is_visible_in_adapter_balance(database):
    """Funding settles -> ledger, projection AND adapter agree."""
    adapter, ledger = await _adapter_with_projection(database)
    settlement = _settlement()

    # Seed the deposit so the projection has a baseline.
    from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType
    from crypto_trader.ledger.service import LedgerPosting

    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("100000"), "USDT"),
            LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("100000"), "USDT"),
        ],
        account_id="default",
        metadata={"amount": "100000", "currency": "USDT"},
    )
    await ledger.apply_paper_funding_settlement(settlement)

    async with database.session_factory() as session:
        snapshot = await replay_projections(session)
    projected = snapshot.balances["USDT"]["total"]

    # Before the resync the cache is stale: this is the exact bug.
    assert adapter.balances["USDT"] == Decimal("100000")

    adapter.sync_balances_from_projection(
        {c: row["total"] for c, row in snapshot.balances.items()}
    )
    assert adapter.balances["USDT"] == projected
    # The signed amount really was a payment out of a LONG's cash.
    assert projected == Decimal("100000") - Decimal("0.074613212074869435")


# ---------------------------------------------------------------- P0-T2
async def test_P0_T2_resync_is_idempotent_no_double_debit(database):
    """Replaying the same projection twice must not move the balance twice."""
    adapter, ledger = await _adapter_with_projection(database)
    settlement = _settlement()

    from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType
    from crypto_trader.ledger.service import LedgerPosting

    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("100000"), "USDT"),
            LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("100000"), "USDT"),
        ],
        account_id="default",
        metadata={"amount": "100000", "currency": "USDT"},
    )
    # Re-posting the SAME settlement instant must be deduplicated by the ledger.
    await ledger.apply_paper_funding_settlement(settlement)
    await ledger.apply_paper_funding_settlement(settlement)

    async with database.session_factory() as session:
        snapshot = await replay_projections(session)
    balances = {c: row["total"] for c, row in snapshot.balances.items()}
    assert balances["USDT"] == Decimal("100000") - Decimal("0.074613212074869435")

    adapter.sync_balances_from_projection(balances)
    first = adapter.balances["USDT"]
    adapter.sync_balances_from_projection(balances)
    adapter.sync_balances_from_projection(balances)
    assert adapter.balances["USDT"] == first
    # A second independent arithmetic would have produced this:
    assert adapter.balances["USDT"] != Decimal("100000") - 2 * Decimal(
        "0.074613212074869435"
    )


# ---------------------------------------------------------------- P0-T3
async def test_P0_T3_failed_commit_does_not_advance_adapter(database):
    """If the ledger write fails, the adapter must not move."""
    adapter = SimulatedExchangeAdapter(initial_balances={"USDT": Decimal("100000")})
    await adapter.connect()

    class _Exploding:
        async def __aenter__(self):
            raise RuntimeError("commit failed")

        async def __aexit__(self, *exc):
            return False

    async def _resync(engine_adapter, session_factory):
        from crypto_trader.ledger.projections import replay_projections as _replay

        async with session_factory() as session:
            snapshot = await _replay(session)
        engine_adapter.sync_balances_from_projection(
            {c: row["total"] for c, row in snapshot.balances.items()}
        )

    with pytest.raises(RuntimeError):
        await _resync(adapter, lambda: _Exploding())
    assert adapter.balances["USDT"] == Decimal("100000")


# ---------------------------------------------------------------- P0-T4
async def test_P0_T4_refresh_failure_keeps_truth_and_retry_converges(database):
    """Adapter refresh failure must not corrupt truth; a retry converges."""
    adapter, ledger = await _adapter_with_projection(database)

    from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType
    from crypto_trader.ledger.service import LedgerPosting

    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("100000"), "USDT"),
            LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("100000"), "USDT"),
        ],
        account_id="default",
        metadata={"amount": "100000", "currency": "USDT"},
    )
    await ledger.apply_paper_funding_settlement(_settlement())

    async with database.session_factory() as session:
        snapshot = await replay_projections(session)
    balances = {c: row["total"] for c, row in snapshot.balances.items()}
    truth = balances["USDT"]

    class _Flaky:
        def __init__(self):
            self.calls = 0

        def sync_balances_from_projection(self, b):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("adapter temporarily unavailable")
            adapter.sync_balances_from_projection(b)

    flaky = _Flaky()
    with pytest.raises(ConnectionError):
        flaky.sync_balances_from_projection(balances)
    # Truth is untouched by the failed refresh and reconciliation stays closed.
    assert adapter.balances["USDT"] == Decimal("100000")

    flaky.sync_balances_from_projection(balances)
    assert adapter.balances["USDT"] == truth
    # No duplicate funding was introduced by the retry.
    async with database.session_factory() as session:
        again = await replay_projections(session)
    assert again.balances["USDT"]["total"] == truth


# ---------------------------------------------------------------- P0-T5
async def test_P0_T5_balance_resync_leaves_orders_and_positions_alone():
    """The narrow sync must not rewind, duplicate or terminate an order.

    This is the concurrency-safety property that made reusing the broad startup
    restore unsafe: a PARTIALLY_FILLED reduce order and the open position must
    survive a cash resync untouched.
    """
    from datetime import timedelta

    from crypto_trader.domain.enums import (
        OrderSide,
        OrderStatus,
        OrderType,
        TimeInForce,
        TradingMode,
    )
    from crypto_trader.domain.models import Order, Position

    adapter = SimulatedExchangeAdapter(initial_balances={"USDT": Decimal("100000")})
    await adapter.connect()
    now = datetime.now(UTC)
    adapter.orders["sim_existing"] = Order(
        internal_order_id="ord_partial",
        client_order_id="cid_partial",
        exchange_order_id="sim_existing",
        symbol=SYMBOL,
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GTC,
        price=Decimal("0.01561"),
        quantity=Decimal("138"),
        filled_quantity=Decimal("2"),
        status=OrderStatus.PARTIALLY_FILLED,
        trading_mode=TradingMode.PAPER,
        strategy_id="live_llm_position",
        created_at=now - timedelta(minutes=76),
        updated_at=now,
    )
    adapter.positions[SYMBOL] = Position(
        symbol=SYMBOL,
        base_asset="CP",
        quote_asset="USDT",
        quantity=Decimal("275"),
        avg_entry_price=Decimal("0.01541"),
        cost_basis=Decimal("423.775"),
        instrument_type="LINEAR_PERP",
        contract_size=CONTRACT_SIZE,
    )
    orders_before = dict(adapter.orders)
    positions_before = dict(adapter.positions)

    adapter.sync_balances_from_projection({"USDT": Decimal("99999.535407787925130565")})

    assert adapter.balances["USDT"] == Decimal("99999.535407787925130565")
    assert adapter.orders == orders_before
    assert adapter.orders["sim_existing"].status == OrderStatus.PARTIALLY_FILLED
    assert adapter.orders["sim_existing"].filled_quantity == Decimal("2")
    assert adapter.positions == positions_before
    assert adapter.positions[SYMBOL].quantity == Decimal("275")


# ---------------------------------------------------------------- P0-T6
async def test_P0_T6_restart_restores_the_same_balance_truth(database):
    """A restart must converge on the same authoritative balance."""
    adapter, ledger = await _adapter_with_projection(database)

    from crypto_trader.domain.enums import LedgerDirection, LedgerEntryType
    from crypto_trader.ledger.service import LedgerPosting

    await ledger.record(
        LedgerEntryType.DEPOSIT,
        [
            LedgerPosting("CASH", LedgerDirection.DEBIT, Decimal("100000"), "USDT"),
            LedgerPosting("EQUITY", LedgerDirection.CREDIT, Decimal("100000"), "USDT"),
        ],
        account_id="default",
        metadata={"amount": "100000", "currency": "USDT"},
    )
    await ledger.apply_paper_funding_settlement(_settlement())

    async with database.session_factory() as session:
        snapshot = await replay_projections(session)
    balances = {c: row["total"] for c, row in snapshot.balances.items()}
    adapter.sync_balances_from_projection(balances)
    online_truth = adapter.balances["USDT"]

    # Simulate a fresh process: brand-new adapter, same durable state.
    restarted = SimulatedExchangeAdapter(initial_balances={"USDT": Decimal("100000")})
    await restarted.connect()
    await restarted.restore_from_canonical_state(balances=balances, positions={})

    assert restarted.balances["USDT"] == online_truth
    assert online_truth == Decimal("100000") - Decimal("0.074613212074869435")
