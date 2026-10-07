# Read-only runtime acceptance diagnostics

`GET /runtime/acceptance` returns the existing engine's current facts.
No attached engine returns 503. No query parameter performs an action.
It does not start tasks, renew leases, write the database, clear health/faults,
change provider pause, or invoke providers. Existing /ready semantics are unchanged.

Actual named asyncio tasks supply worker states/counts. The central predicate
and diagnostics share one evaluator, not configured worker counts or cached
aggregate health. Lease observations use the existing committed read-only row
lookup and post-read expiry clock. `checked_epoch` explicitly means the existing
execution guard's UTC clock after that committed read, not an invented SQL clock.
The token is a SHA256 opaque identifier, never a credential.

The real execution guard has sticky lease-loss side effects. If current lease
evaluation would require them, GET does not invoke them or publish an approximate
central result: `trading_safety_failures=null` and
`trading_safety_evaluation_error=CENTRAL_PREDICATE_REQUIRES_LEASE_LOSS_SIDE_EFFECT`.
This is unavailable evidence, never an empty list/PASS. Current lease facts and
their bounded error remain explicit; an old first eligibility cannot grant
current authority.

The first actual empty execution predicate captures its original lease check,
settlement observation, task topology and UTC once, synchronously without await.
GET cannot create it. Returned copies cannot change it. A later fault/recovery
does not overwrite it. A new engine/process starts with null. Collection failure
does not affect trading; it remains CAPTURE_UNAVAILABLE, never re-stamped later.
Source identity remains separately bound by the exact-SHA identity bridge.

This surface grants no boot, provider restoration, qualification or soak credit.
