"""Unified domain error model. Core never parses exchange-specific error codes."""

from __future__ import annotations


class CryptoTraderError(Exception):
    pass


class ExchangeError(CryptoTraderError):
    pass


class ExchangeUnavailable(ExchangeError):
    pass


class RateLimited(ExchangeError):
    pass


class AuthenticationError(ExchangeError):
    pass


class InvalidOrder(ExchangeError):
    pass


class InsufficientBalance(ExchangeError):
    pass


class OrderNotFound(ExchangeError):
    pass


class OrderRejected(ExchangeError):
    pass


class StaleMarketData(ExchangeError):
    pass


class SequenceGap(ExchangeError):
    pass


class TemporaryNetworkError(ExchangeError):
    pass


class UnknownExecutionState(ExchangeError):
    pass


class IdempotencyConflict(CryptoTraderError):
    pass


class InvalidStateTransition(CryptoTraderError):
    pass


class JournalUnbalanced(CryptoTraderError):
    pass


class LeaseNotHeld(CryptoTraderError):
    pass


class KillSwitchEngaged(CryptoTraderError):
    pass


class MarketDataUnhealthy(CryptoTraderError):
    pass
