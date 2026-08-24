# HARNESS_GOAL

Create an Exchange-independent, Event-driven, Ledger-first, Idempotent, Recoverable
Crypto Automated Trading Infrastructure.

Trading strategy is not the core goal.

Success criteria:
- reliable execution
- recoverable after crash/restart
- never duplicate orders for the same client_order_id
- ledger always journal-balanced and replayable
- decimal precision correct in all money paths
- market data reliable with sequence-gap resync
- exchange adapters replaceable (Binance first; OKX/Bybit boundaries)
- paper and live share one core (LIVE / PAPER / SHADOW)
