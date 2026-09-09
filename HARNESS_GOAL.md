# HARNESS_GOAL

## Current user-approved goal (2026-09-09)

Read [AI-native remediation master instructions](docs/ai-native-remediation/MASTER_HARNESS_INSTRUCTIONS.md)
and start with chapter 00 only. Harness implements; Codex independently reviews and
approves each exact candidate SHA. Waiting for review permits read-only preparation,
not implementation of the next chapter. Harness recovery never authorizes restarting
the trading runtime. Chapter 00 communication/recovery is not yet verified.

Canonical direction authority is ChiefTraderEngine / DeepSeekProvider only.
Quant/factor/strategy/research/memory are evidence tools. Risk may APPROVE,
SCALE_DOWN, or REJECT, never reverse direction. Execution enforces safety.
PAPER ONLY, real OKX public data and local simulation. No LIVE, forced trades,
synthetic fallback, fabricated episodes, risk bypass, or duplicate writers.

## Historical infrastructure goal (reference only)

The following original text is preserved for provenance. Its Binance-first,
strategy-not-core and LIVE/PAPER scope statements are superseded by the current
goal above. Reuse its valid event-driven, ledger-first, idempotency and recovery
requirements; do not treat historical scope as authorization.

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
