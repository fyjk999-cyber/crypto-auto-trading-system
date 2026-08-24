"""Decimal-safe financial arithmetic.

Python port of the semantic ideas in Kalshi v2 lib/v2/decimal.mjs
(string-only parsing, explicit precision, no binary float) implemented with
Python decimal.Decimal. Binary float is forbidden in core financial fields.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP, localcontext
from typing import Annotated, Any

from pydantic import BeforeValidator

DEFAULT_QUANTUM = Decimal("0.00000001")
ZERO = Decimal("0")


class DecimalError(ValueError):
    pass


def D(value: Any) -> Decimal:
    """Convert int/str/Decimal to Decimal. Binary float is rejected."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise DecimalError("boolean is not a decimal value")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            raise DecimalError("empty decimal string")
        try:
            with localcontext() as ctx:
                ctx.prec = 40
                parsed = Decimal(text)
        except InvalidOperation as exc:
            raise DecimalError(f"invalid decimal string: {value!r}") from exc
        if not parsed.is_finite():
            raise DecimalError("decimal must be finite")
        return parsed
    if isinstance(value, float):
        raise DecimalError(
            "binary float is forbidden in financial core; convert at adapter boundary "
            "with Decimal(str(raw_value))"
        )
    raise DecimalError(f"unsupported decimal input type: {type(value).__name__}")


def _validate_strict_decimal(value: Any) -> Decimal:
    return D(value)


StrictDecimal = Annotated[Decimal, BeforeValidator(_validate_strict_decimal)]
Money = StrictDecimal
Price = StrictDecimal
Quantity = StrictDecimal
Balance = StrictDecimal
Fee = StrictDecimal
PnL = StrictDecimal
CostBasis = StrictDecimal
Margin = StrictDecimal
Funding = StrictDecimal
Decimal8 = StrictDecimal


def quantize_8(value: Any, rounding: str = ROUND_HALF_UP) -> Decimal:
    return D(value).quantize(DEFAULT_QUANTUM, rounding=rounding)


def format_decimal(value: Any) -> str:
    d = D(value)
    if d == 0:
        return "0"
    q = d.quantize(DEFAULT_QUANTUM)
    text = format(q, "f") if q == d else format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def round_tick(value: Any, tick_size: Any, rounding: str = ROUND_HALF_UP) -> Decimal:
    tick = D(tick_size)
    if tick <= 0:
        raise DecimalError("tick size must be positive")
    return D(value).quantize(tick.normalize(), rounding=rounding)


def floor_to_step(value: Any, step_size: Any) -> Decimal:
    step = D(step_size)
    if step <= 0:
        raise DecimalError("step size must be positive")
    with localcontext() as ctx:
        ctx.prec = 60
        value_d = D(value)
        steps = (value_d / step).to_integral_value(rounding=ROUND_DOWN)
        return steps * step


def is_zero(value: Any) -> bool:
    return D(value) == 0


def safe_mul(left: Any, right: Any) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 60
        return D(left) * D(right)


def safe_div(left: Any, right: Any) -> Decimal:
    divisor = D(right)
    if divisor == 0:
        raise DecimalError("division by zero")
    with localcontext() as ctx:
        ctx.prec = 60
        return D(left) / divisor
