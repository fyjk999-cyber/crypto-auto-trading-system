# Additive active-cycle readiness guard

Exact base: 3cfee4807fcc801e1c345b9d877063c587f40658. The successor SHA is the
commit containing this document, bound by its external engineering receipt.
The old3cfee source remains immutable historical provenance.

Shared History publishes the new explicit independent300s active liveness
contract under operational_health.incremental. One existing authoritative
operational_health_failure predicate serves readiness and runtime adapter.
Both current UTC age and producer monotonic stale evidence must be safe;
missing/invalid/contradictory metadata fails closed. Active=false requires null
current id/start/age and stale=false. A normal current active cycle is permitted.

No legacy gate is replaced: completed PASS, resourceNORMAL/current60s,
scheduler running/current60s, single writer and independently current full
dynamic eligible universe maxlag300/outside0 remain required. Producer WAITING
continues to fail closed. No writes, LLM resume, memory or trading authority are
added. Chief directional and Risk hard-safety authority remain unchanged.

Producer golden fixture bytes are consumed unchanged by consumer tests. Deploy
and accept the producer successor first, then prepare exact successor LowRisk
preboot/rollback artifacts. This phase DOES NOT install/boot LowRisk; activation
requires a later complete bound stage instruction and fresh exact-SHA gates.
Never activate old baselines automatically, reuse old soak credit, or count
synthetic fixture/isolated test results as production lifecycle evidence.
