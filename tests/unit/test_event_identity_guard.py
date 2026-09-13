"""Fail-closed guarantees for the exchange-event identity guard.

`process_exchange_event` refuses an event whose payload contradicts the order it
resolved to. Two opposite mistakes are possible and both are pinned here:

* TOO STRICT - byte-equality on symbols refuses every event for an order whose
  venue naming form differs from the local one, which wedges the trade plan at
  APPROVED (the symptom the lifecycle fix removes).
* TOO LOOSE - trusting a normalizer that is missing, raises, or returns a
  constant accepts every pair and silently disables the guard.

The rule under test: accept a naming variant; refuse a genuinely different
symbol; and when the adapter cannot answer canonically, fall back to a
case-insensitive comparison, which fails closed.
"""

from __future__ import annotations

from crypto_trader.exchange.okx import OKXAdapter
from crypto_trader.runtime.engine import _same_symbol
from crypto_trader.simulator.exchange import SimulatedExchangeAdapter

LOCAL = "BTCUSDT"


class _Degenerate:
    def normalize_symbol(self, raw):  # noqa: ARG002
        return None


class _Constant:
    def normalize_symbol(self, raw):  # noqa: ARG002
        return "SAME"


class _Raiser:
    def normalize_symbol(self, raw):
        raise ValueError(f"unknown exchange symbol: {raw}")


class _NoNormalizer:
    pass


def _okx() -> OKXAdapter:
    return OKXAdapter.__new__(OKXAdapter)  # normalize_symbol needs no network


def test_a_naming_variant_is_accepted() -> None:
    sim = SimulatedExchangeAdapter()
    okx = _okx()
    # Case variants are the same instrument for every adapter.
    assert _same_symbol(sim, "btcusdt", LOCAL) is True
    assert _same_symbol(okx, "btcusdt", LOCAL) is True
    assert _same_symbol(_Raiser(), "btcusdt", LOCAL) is True
    assert _same_symbol(_NoNormalizer(), "btcusdt", LOCAL) is True
    # A hyphenated venue form is resolved by the adapter that owns the mapping.
    assert _same_symbol(okx, "BTC-USDT-SWAP", LOCAL) is True
    assert _same_symbol(okx, "btc-usdt-swap", LOCAL) is True


def test_a_different_symbol_is_always_refused() -> None:
    for adapter in (
        SimulatedExchangeAdapter(),
        _okx(),
        _Degenerate(),
        _Constant(),
        _Raiser(),
        _NoNormalizer(),
    ):
        for payload in ("ETHUSDT", "ethusdt", "ETH-USDT-SWAP", "BCHUSDT"):
            assert _same_symbol(adapter, payload, LOCAL) is False, (
                type(adapter).__name__,
                payload,
            )


def test_a_degenerate_normalizer_cannot_disable_the_guard() -> None:
    """The dangerous direction: a normalizer that answers nothing.

    ``_Constant`` maps an impossible sentinel onto the local symbol, which is how
    the guard detects that it is not discriminating.
    """
    assert _same_symbol(_Degenerate(), "ETHUSDT", LOCAL) is False
    assert _same_symbol(_Constant(), "ETHUSDT", LOCAL) is False
    assert _same_symbol(_NoNormalizer(), "ETHUSDT", LOCAL) is False


def test_an_unrenderable_symbol_is_not_a_match() -> None:
    class Hostile:
        def __str__(self) -> str:
            raise RuntimeError("no")

    assert _same_symbol(SimulatedExchangeAdapter(), Hostile(), LOCAL) is False
