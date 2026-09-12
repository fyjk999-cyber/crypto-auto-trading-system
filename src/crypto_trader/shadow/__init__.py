"""Isolated shadow (counterfactual) learning sidecar.

HARD BOUNDARIES — these are architectural, not stylistic:

* The realtime trading path NEVER waits for this package. Candidates are
  enqueued only AFTER a ChiefTrader decision is already committed.
* ``SHADOW_LLM_CALLS == 0``. Nothing here calls a provider; the real 120/hour
  LLM budget (60 position reserve + 60 general pool) is untouched.
* Position capacity, account balance, orders, fills and the funding ledger are
  never written. Shadow rows live in their own namespace.
* Shadow data is NEVER factual: ``factual = False`` and
  ``evidence_type = SHADOW_EPISODE`` are set on every shadow episode.
* Market data is READ-ONLY. Shadow consumes observations the runtime already
  produced; it never becomes a second exchange poller.
* Failure policy is the opposite of trading: real trading fails CLOSED, shadow
  fails OPEN toward real trading. A shadow error is recorded and dropped and
  real trading continues.
"""

from crypto_trader.shadow.eligibility import (
    ShadowEligibility,
    shadow_eligibility,
)

__all__ = ["ShadowEligibility", "shadow_eligibility"]
