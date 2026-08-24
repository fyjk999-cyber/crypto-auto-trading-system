from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from crypto_trader.domain.money import (
    D,
    DecimalError,
    Money,
    Price,
    Quantity,
    floor_to_step,
    format_decimal,
    quantize_8,
    round_tick,
)


class MoneyModel(BaseModel):
    price: Price
    quantity: Quantity
    amount: Money


def test_decimal_accepts_str_int_decimal():
    assert D("1.25") == Decimal("1.25")
    assert D(7) == Decimal("7")
    assert D(Decimal("0.1")) == Decimal("0.1")


def test_decimal_rejects_float_and_bool():
    with pytest.raises(DecimalError):
        D(0.1)
    with pytest.raises(DecimalError):
        D(True)


def test_decimal_exactness_no_binary_float_error():
    # 0.1 + 0.2 exact in decimal, unlike binary float
    assert D("0.1") + D("0.2") == D("0.3")


def test_pydantic_rejects_float_financial_fields():
    with pytest.raises(ValidationError):
        MoneyModel(price=0.1, quantity="1", amount="10")
    m = MoneyModel(price="0.1", quantity="1", amount=10)
    assert m.price == Decimal("0.1")
    assert isinstance(m.amount, Decimal)


def test_quantize_8():
    assert quantize_8("0.123456789") == Decimal("0.12345679")
    assert quantize_8("3") == Decimal("3.00000000")


def test_format_decimal_removes_trailing_zeros():
    assert format_decimal("1.50000000") == "1.5"
    assert format_decimal("0.00000000") == "0"


def test_round_tick():
    assert round_tick("123.4567", "0.01") == Decimal("123.46")
    assert round_tick("123.4567", "0.01", "ROUND_DOWN") == Decimal("123.45")


def test_floor_to_step():
    assert floor_to_step("1.2345", "0.001") == Decimal("1.234")
    assert floor_to_step("2", "0.5") == Decimal("2.0")


def test_floor_to_step_rejects_nonpositive_step():
    with pytest.raises(DecimalError):
        floor_to_step("1", "0")
