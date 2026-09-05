from decimal import Decimal

import pytest
from pydantic import ValidationError

from crypto_trader.exposure.service import ExposureService, InstrumentExposureSpec
from crypto_trader.perpetual.domain import (
    ContractType,
    MarginPosition,
    PerpetualContract,
    PositionSide,
)
from crypto_trader.perpetual.funding import FundingCalculator
from crypto_trader.perpetual.liquidation import LiquidationCalculator
from crypto_trader.perpetual.margin import MarginCalculator, MarginState


def make_contract(symbol="BTCUSDT_PERP"):
    return PerpetualContract(
        symbol=symbol,
        instrument_type=ContractType.PERPETUAL,
        base="BTC",
        quote="USDT",
        settlement_asset="USDT",
        contract_size=Decimal("1"),
        tick_size=Decimal("0.01"),
        quantity_step=Decimal("0.001"),
        max_leverage=Decimal("6"),
    )


def make_position(side=PositionSide.LONG, qty="1", entry="100", lev="5"):
    contract = make_contract()
    calc = MarginCalculator()
    im = calc.initial_margin(contract, Decimal(qty), Decimal(entry), Decimal(lev))
    mm = calc.maintenance_margin(contract, Decimal(qty), Decimal(entry))
    pos = MarginPosition(
        symbol=contract.symbol,
        side=side,
        quantity=Decimal(qty) if side == PositionSide.LONG else -Decimal(qty),
        avg_entry_price=Decimal(entry),
        leverage=Decimal(lev),
        initial_margin=im,
        maintenance_margin=mm,
    )
    return contract, calc, pos


def test_perpetual_domain_is_decimal_only():
    contract = make_contract()
    assert contract.tick_size == Decimal("0.01")
    with pytest.raises(ValidationError):
        PerpetualContract(
            symbol="X",
            base="X",
            quote="USDT",
            settlement_asset="USDT",
            tick_size=0.01,
        )


def test_instrument_separation_spot_vs_perpetual():
    assert make_contract().instrument_type == ContractType.PERPETUAL
    assert make_contract().instrument_type != ContractType.SPOT


def test_margin_initial_maintenance_available():
    contract, calc, pos = make_position()
    assert pos.initial_margin == Decimal("20")  # 100/5
    assert pos.maintenance_margin == Decimal("0.1")  # 100*0.001
    state = MarginState(balance=Decimal("1000"), positions=[pos])
    assert calc.available_margin(state, Decimal("1000")) == Decimal("980")
    ratio = calc.margin_ratio(state, Decimal("1000"))
    assert ratio.healthy


def test_margin_leverage_capped_at_contract_max():
    contract = make_contract()
    calc = MarginCalculator()
    assert calc.effective_leverage(Decimal("10"), contract.max_leverage) == Decimal("6")
    im = calc.initial_margin(contract, Decimal("1"), Decimal("100"), Decimal("10"))
    assert im == Decimal("100") / Decimal("6")


def test_liquidation_price_long_and_short():
    contract, calc, pos_long = make_position(PositionSide.LONG)
    liq = LiquidationCalculator()
    lp = liq.liquidation_price(pos_long, contract)
    assert lp.value < Decimal("100")
    contract2, calc2, pos_short = make_position(PositionSide.SHORT)
    lp2 = liq.liquidation_price(pos_short, contract2)
    assert lp2.value > Decimal("100")


def test_liquidation_evaluate_long_and_short():
    contract, calc, pos_long = make_position(PositionSide.LONG)
    liq = LiquidationCalculator()
    res = liq.evaluate(pos_long, contract, Decimal("80"))
    assert res.liquidated is True
    assert res.remaining_equity >= 0
    contract2, calc2, pos_short = make_position(PositionSide.SHORT)
    res2 = liq.evaluate(pos_short, contract2, Decimal("120"))
    assert res2.liquidated is True


def test_funding_long_pays_short_receives():
    calc = FundingCalculator()
    pos_long = make_position(PositionSide.LONG)[2]
    pos_short = make_position(PositionSide.SHORT)[2]
    p_long = calc.payment(pos_long, Decimal("0.0001"), Decimal("100"), Decimal("1"))
    p_short = calc.payment(pos_short, Decimal("0.0001"), Decimal("100"), Decimal("1"))
    assert p_long.amount == -p_short.amount
    assert p_long.amount < 0
    assert p_short.amount > 0


def test_perpetual_consumers_share_canonical_contract_size_notional():
    contract = make_contract()
    contract.contract_size = Decimal("0.01")
    quantity = Decimal("2")
    price = Decimal("50000")
    canonical = ExposureService.calculate(
        quantity=quantity,
        price=price,
        spec=InstrumentExposureSpec(
            instrument_type="LINEAR_PERP",
            contract_size=contract.contract_size,
        ),
        side="LONG",
    ).gross_notional
    assert canonical == Decimal("1000.00")

    margin = MarginCalculator()
    assert margin.initial_margin(contract, quantity, price, Decimal("5")) == canonical / 5
    assert margin.maintenance_margin(contract, quantity, price) == canonical * Decimal(
        "0.001"
    )

    position = MarginPosition(
        symbol=contract.symbol,
        side=PositionSide.LONG,
        quantity=quantity,
        avg_entry_price=price,
    )
    payment = FundingCalculator().payment(
        position, Decimal("0.0001"), price, contract.contract_size
    )
    assert payment.notional == canonical
