"""P1: one valuation truth batch for Sizing, Risk, Portfolio and API."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from crypto_trader.api.app import create_app
from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import Account, Instrument, SignalIntent
from crypto_trader.ledger.service import LedgerService
from crypto_trader.persistence.models import EquitySnapshotORM, ValuationBatchORM
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.sizing.service import LiveEntrySizingService
from crypto_trader.valuation.domain import ValuationBatch
from crypto_trader.valuation.service import ValuationService
from tests.conftest import make_paper_engine
from tests.integration.test_api import make_state


def _instrument() -> Instrument:
    return Instrument(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        instrument_type="LINEAR_PERP",
        contract_size="1",
        step_size="0.001",
    )


def _batch(
    *,
    equity: str = "1000",
    margin: str = "500",
    quality: str = "HEALTHY",
) -> ValuationBatch:
    return ValuationBatch(
        valuation_id="val-p1-test",
        account_id="default",
        currency="USDT",
        quality=quality,
        raw_mtm_equity=Decimal(equity) if quality == "HEALTHY" else None,
        available_margin=Decimal(margin) if quality == "HEALTHY" else None,
    )


def test_sizing_uses_batch_equity_and_available_margin():
    sizer = LiveEntrySizingService(
        risk_fraction=Decimal("0.5"),
        max_order_notional=Decimal("1000000"),
        max_leverage=Decimal("5"),
    )
    common = dict(
        side="LONG",
        requested_quantity=Decimal("100"),
        requested_leverage=Decimal("1"),
        account=Account(equity=Decimal("100000")),
        positions={},
        instrument=_instrument(),
        price=Decimal("100"),
        stop_price=Decimal("90"),
    )
    without_batch = sizer.size(**common)
    with_batch = sizer.size(**common, valuation=_batch(equity="1000", margin="500"))
    # The batch equity (not account.equity) drives the risk budget.
    assert with_batch.sizing_equity == Decimal("1000")
    assert with_batch.valuation_id == "val-p1-test"
    assert with_batch.available_margin == Decimal("500")
    assert with_batch.normalized_quantity < without_batch.normalized_quantity


def test_sizing_refuses_unavailable_or_unfunded_batch():
    sizer = LiveEntrySizingService(
        risk_fraction=Decimal("0.01"),
        max_order_notional=Decimal("10000"),
        max_leverage=Decimal("3"),
    )
    common = dict(
        side="LONG",
        requested_quantity=Decimal("1"),
        requested_leverage=Decimal("1"),
        account=Account(equity=Decimal("10000")),
        positions={},
        instrument=_instrument(),
        price=Decimal("100"),
        stop_price=Decimal("95"),
    )
    unavailable = sizer.size(
        **common, valuation=_batch(quality="UNAVAILABLE")
    )
    assert unavailable.normalized_quantity == 0
    assert unavailable.sizing_reason_codes == ("VALUATION_BATCH_UNAVAILABLE",)

    no_margin = sizer.size(**common, valuation=_batch(equity="10000", margin="0"))
    assert no_margin.normalized_quantity == 0
    assert no_margin.sizing_reason_codes == ("INSUFFICIENT_AVAILABLE_MARGIN",)


async def test_first_unavailable_never_seeds_peak_and_ratio_is_canonical(database):
    service = PortfolioService(database.session_factory)
    missing = ["BTC-USDT-SWAP"]
    drawdown, peak, _, _ = await service.record_equity_drawdown(
        Decimal("100"),
        quality="UNAVAILABLE",
        reason_codes=["VALUATION_UNAVAILABLE"],
        missing_marks=missing,
    )
    assert drawdown is None
    assert peak is None
    async with database.session_factory() as session:
        batch = (await session.execute(select(ValuationBatchORM))).scalar_one()
        snapshot = (await session.execute(select(EquitySnapshotORM))).scalar_one()
    assert batch.peak_adjusted_equity is None
    assert batch.drawdown_amount is None
    assert batch.drawdown_ratio is None
    assert batch.raw_mtm_equity is None
    assert batch.available_margin is None
    assert batch.quality == "UNAVAILABLE"
    assert batch.missing_marks_json == missing
    assert batch.solvency is None
    assert snapshot.peak_adjusted_equity is None
    assert snapshot.drawdown is None
    assert snapshot.valuation_status == "UNAVAILABLE"

    # First HEALTHY batch establishes the baseline.
    drawdown, peak, _, _ = await service.record_equity_drawdown(Decimal("120"))
    assert peak == Decimal("120")
    assert drawdown == Decimal("0")
    # A later unavailable valuation must not move peak or create drawdown.
    drawdown, peak, _, _ = await service.record_equity_drawdown(
        Decimal("200"), quality="UNAVAILABLE", reason_codes=["VALUATION_UNAVAILABLE"]
    )
    assert peak == Decimal("120")
    assert drawdown is None
    # Next healthy valuation computes the canonical ratio.
    drawdown, peak, _, _ = await service.record_equity_drawdown(Decimal("90"))
    assert peak == Decimal("120")
    assert drawdown == Decimal("-30")
    async with database.session_factory() as session:
        batch = (
            await session.execute(
                select(ValuationBatchORM).order_by(ValuationBatchORM.created_at.desc())
            )
        ).scalars().first()
    assert batch.drawdown_ratio == Decimal("-0.25")


async def test_valuation_service_persists_immutable_batch_with_refs(database):
    portfolio = PortfolioService(database.session_factory)
    ledger = LedgerService(database.session_factory)
    service = ValuationService(portfolio=portfolio, ledger=ledger)
    account = Account(account_id="default", equity=Decimal("1000"))
    batch = await service.build(
        account=account,
        positions={},
        market_prices={},
        instruments={},
        market_as_of=datetime.now(UTC),
    )
    assert batch.ledger_watermark is None  # no verified ledger rows yet
    persisted = await service.persist(batch, fallback_equity=account.equity)
    assert persisted.valuation_id == batch.valuation_id
    assert persisted.position_snapshot_ref == batch.position_snapshot_ref
    loaded = await service.get(batch.valuation_id)
    assert loaded is not None
    assert loaded.raw_mtm_equity == Decimal("1000")
    assert loaded.quality == "HEALTHY"


async def test_engine_sizing_and_risk_share_same_valuation_id(database):
    class ValuationAwareStrategy:
        name = "p1_valuation_probe"
        version = "1.0.0"
        symbol = "BTCUSDT"

        def __init__(self) -> None:
            self.seen = None

        def desired_symbol(self) -> str:
            return "BTCUSDT"

        async def on_market_data(self, ctx):
            self.seen = ctx.valuation
            mid = ctx.book.mid_price() or Decimal("100")
            return [
                SignalIntent(
                    signal_id="p1-signal",
                    strategy_id=self.name,
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    quantity=Decimal("0.1"),
                    limit_price=mid,
                    metadata={
                        "direction": "LONG",
                        "valuation_id": (
                            ctx.valuation.valuation_id if ctx.valuation else None
                        ),
                    },
                )
            ]

    strategy = ValuationAwareStrategy()
    engine = make_paper_engine(database, strategy=strategy, engine_tick_seconds=3600)
    try:
        await engine.start("run-p1-valuation")
        decisions = await engine.tick()
        assert strategy.seen is not None
        assert strategy.seen.quality == "HEALTHY"
        assert decisions
        decision = decisions[0]
        assert decision.checks["valuation_id"] == strategy.seen.valuation_id
        assert decision.checks["valuation_quality"] == "HEALTHY"
        persisted = await engine.portfolio.get_valuation_batch(
            strategy.seen.valuation_id
        )
        assert persisted is not None
        assert persisted.raw_mtm_equity == strategy.seen.raw_mtm_equity
        assert decision.checks["available_margin"] == (
            str(persisted.available_margin)
            if persisted.available_margin is not None
            else None
        )
    finally:
        await engine.stop()


async def test_api_account_and_margin_return_same_valuation_id(database):
    state = make_state(database)
    await state.portfolio.refresh(initial_balances={"USDT": Decimal("1000")})
    await state.portfolio.record_equity_drawdown(Decimal("1000"))
    client = TestClient(create_app(state))
    account = client.get("/account").json()
    margin = client.get("/margin").json()
    assert account["valuation"]["valuation_id"] is not None
    assert account["valuation"]["valuation_id"] == margin["valuation"]["valuation_id"]
    assert account["valuation"]["quality"] == "HEALTHY"
    assert account["valuation"]["raw_mtm_equity"] == "1000"


async def test_api_without_valuation_is_explicitly_unavailable(database):
    state = make_state(database)
    client = TestClient(create_app(state))
    payload = client.get("/account").json()
    assert payload["valuation"]["quality"] == "UNAVAILABLE"
    assert payload["valuation"]["valuation_id"] is None
    assert payload["valuation"]["raw_mtm_equity"] is None
    assert payload["valuation"]["reason_codes"] == ["NO_VALUATION_BATCH"]
