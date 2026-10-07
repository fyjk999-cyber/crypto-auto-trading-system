# Authoritative execution lease (Round18 successor)

The runtime's lease object is a grant identity, not proof of current ownership.
The committed `runtime_leases` row owns the current owner/token/fence/expiry.
Default policy remains **TTL10s / renew3s**; no startup grace period is added.

## Startup and loss

Startup acquires before authoritative writes and starts heartbeat immediately.
The first renewal must succeed before recovery begins. Startup state, factual
recovery, settlement, required legs, account reconciliation and workers remain
independent trading gates. Heartbeat alone does not make execution eligible.

Expired authority cannot renew, including same-owner expiry and expiry during
an awaited SQL/lock window. Native SQL execution-time clocks validate renewal
and acquisition. Reacquisition advances token/fence; a failed running engine
cannot silently resume by calling start again. A fresh runtime must rerun all
startup safety gates. Lease loss never automatically clears the kill switch.

## Three execution boundaries

1. Central safety and runtime lease telemetry read the committed row afresh.
   SQLite reads have a bounded 50ms lock wait, followed by expiry validation;
   unavailable evidence fails closed with no cached-true fallback. PostgreSQL
   reader connections are read-only with bounded connect/statement deadlines.
2. Runtime services use actor-bound sessions. Each session captures its grant
   at creation; another actor's factory/grant cannot be borrowed. A conditional
   no-op lease UPDATE locks that row in the **same** mutation transaction.
   ORM flushes and bulk DML validate ownership; commit flushes all pending DML
   then revalidates expiry. Failed authority rolls back the transaction and
   latches runtime safety failure. The lock never extends TTL or changes fence.
3. Native PAPER submission checks central safety after submit awaits; matching
   rechecks lease after durable settlement begin and before each account fill.
   Cancellation also requires lease. Direct perpetual API monetary writes use
   the same actor-bound sessions plus central execution guard, not an API-local
   unfenced ledger. Lease denial produces HTTP409 without secret/SQL details.

Only append-only EXECUTION_LEASE_LOST/ENGINE_STOPPED diagnostics and **own-run**
STOPPED metadata may persist after loss. They cannot close other runtime rows,
create orders/fills/episodes, alter balances, or grant trading authority.
Recovery/FILL_SETTLED/settlement journal writes are not exempt.

## Acceptance scope

Engine-level startup/order/ledger/portfolio/plan/episode/leg/reconciliation writes
are fenced; bootstrap binds Chief decision/evidence stores to that same actor.
Standalone tools and isolated test fixture writers have their own explicit
factories, not runtime grants. Required tests cover expired and superseded
writers, last-DML rollback, sticky failure, long startup, native matching and
alternate risk APIs. Historical tests permitting old-token expiry resurrection
are superseded by the explicitly stricter Round18 contract.

This engineering change does not authorize production boot/deployment, DB
repair, forced position action, provider calls, qualification, or soak.
Current-SHA CI, independent critical review and a new bound final-preboot review
are required before any later controlled PAPER activation.
