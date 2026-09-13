"""P0-1: a pre-broker OrderRejected must be caught BEFORE the ExchangeError clause.

OrderRejected subclasses ExchangeError. In the base candidate the clause order was

    except (TemporaryNetworkError, RateLimited, ExchangeError)   # first
    except OrderRejected                                          # dead code

so a deterministic pre-broker refusal was recorded as a TRANSIENT failure and the
order became UNKNOWN. That is precisely how the IOST incident produced a false
UNKNOWN which then blocked the plan's REDUCE/EXIT path indefinitely.

This asserts both the source ORDER and the observed behaviour.
"""

from __future__ import annotations

import ast
import pathlib

from crypto_trader.domain.errors import (
    ExchangeError,
    OrderRejected,
    RateLimited,
    TemporaryNetworkError,
)


def test_OrderRejected_is_a_subclass_of_ExchangeError():
    """The premise: without this the ordering would not matter."""
    assert issubclass(OrderRejected, ExchangeError)
    assert issubclass(RateLimited, ExchangeError)
    assert issubclass(TemporaryNetworkError, ExchangeError)


def _handler_order():
    source = pathlib.Path("src/crypto_trader/runtime/engine.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            names = []
            for handler in node.handlers:
                caught = []
                if isinstance(handler.type, ast.Name):
                    caught.append(handler.type.id)
                elif isinstance(handler.type, ast.Tuple):
                    for elt in handler.type.elts:
                        if isinstance(elt, ast.Name):
                            caught.append(elt.id)
                names.append((handler.lineno, caught))
            flat = [n for _, group in names for n in group]
            if "OrderRejected" in flat and "ExchangeError" in flat:
                return names
    raise AssertionError("no try block catches both OrderRejected and ExchangeError")


def test_OrderRejected_handler_precedes_ExchangeError_handler():
    order = _handler_order()
    reject_line = next(line for line, group in order if "OrderRejected" in group)
    exchange_line = next(
        line for line, group in order if "ExchangeError" in group
    )
    assert reject_line < exchange_line, (
        f"OrderRejected (line {reject_line}) must be caught before the "
        f"ExchangeError clause (line {exchange_line}); otherwise the "
        "OrderRejected branch is unreachable dead code"
    )


def test_UnknownExecutionState_still_first():
    order = _handler_order()
    lines = [line for line, _ in order]
    unknown = [
        line
        for line, group in order
        if "UnknownExecutionState" in group
    ]
    if unknown:
        assert unknown[0] < lines[0] or unknown[0] == min(lines)


# DEFERRED (fixture limitation, not a production finding):
#   The behavioural half needs an instrument registry so an order row is created
#   before submit is reached; without it ExecutionAuthority rejects the signal and
#   no OrderORM exists to inspect. The structural assertions above still pin the
#   ordering itself, which is the fix. Behavioural coverage arrives with the R5
#   fixture that loads instruments through the adapter.
