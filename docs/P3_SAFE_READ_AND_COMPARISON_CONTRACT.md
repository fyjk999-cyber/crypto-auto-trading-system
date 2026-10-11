# P3 isolated read boundary and comparison contract V1

## Safe inventory

The S2 predicate source at811eaa294b84158b24ea3cf92fa1f1890ca4f040 is retained
under evidence-v2/verification/s2_contracts.py, not installed. Its exact seven core
labels and exact admitted auxiliary identities remain unchanged. Its metadata
reader only uses lstat; all content/lock opens are denied. Unknown services, two
distinct writer PIDs or identity changes fail. Multiple FDs from one PID count once.
No command runner, service controls, API mutation, credential or DB reader is added.

## Production factual reads — blocked

Before production admission, specify all fields in DATA_READ_REQUIREMENTS: owner,
exact source/snapshot hash, owner-produced committed-WAL-consistent snapshot and
provenance/cutoff, freshness, units/timestamps, read-only identity, byte/memory/time
limits, cancellation/recovery, sidecar policy and demonstrated writer noninterference.
Confirm that snapshot publication is by the authorized data owner, with unique
writer and authenticated version publication. No caller approval string certifies
these facts. The candidate always returns BLOCKED_UNTIL_PRODUCTION_ADMISSION.

Only supplied fake-byte budget/hash checks and temporary fake SQLite WAL→backup
tests run this round. The backup includes a committed fixture row with its fake
writer open; it is not a production connector or proof of the ~734MB production
DB cost, locking, sidecars or workload. Tracemalloc measurements are Python-memory
measurements for an8MiB fake buffer, not OS peak RSS or production throughput.
FULL_VERIFY_ALL stays NOT_ACCEPTED; the old wrapper is not executed or replaced.

## Offline comparison export — disabled by default

No runtime caller, endpoint, config, scheduler or Quant Core connection is added.
comparison_record rejects calls unless an explicit offline invocation opts in.
It serializes only supplied values and provenance strings; all populated values
remain CALLER_SUPPLIED_NOT_RUNTIME_VERIFIED. Unknown values are NOT_AVAILABLE with
null, not zero/blank/fake IDs. This is not authentication of arbitrary caller facts.
Schema v1 includes the17 fields listed in P3E. Monetary values are finite decimal
strings in one account quote currency; fees are costs, funding is signed funding PnL.
Do not compare different currencies or timestamps without a later approved mapper.

Existing source mapping, not executed database access:
- decision_id/llm_decision: LLMDecisionORM.decision_id/action.
- risk_decision: RiskDecisionORM/recorded decision, not a newly computed risk verdict.
- paper_order_id/fill_id: existing OrderORM/FillORM IDs; never construct absent IDs.
- episode_id/gross_pnl/net_pnl/fees/funding: TradeEpisodeORM, funding_pnl is signed.
  Existing trade_episode.py computes net=gross-fees+funding_pnl; this is the schema
  accounting parity rule, not verification that every current funding value is factual.
- market_asof_utc: later mapper must take the existing factual market observation time,
  not serialization time. No such live mapper or snapshot has been admitted here.
- strategy_package_hash/factor_schema_version/factor_snapshot_hash/experiment_id:
  NOT_AVAILABLE unless a provenance-bound existing record is later supplied.
- equity/drawdown: NOT_AVAILABLE without an approved factual account observation.

Actual zero is legitimate only as a sourced decimal fact; no missing field is filled
with it. Source-ID text cannot manufacture runtime acceptance. No order, account,
ledger-write or strategy-switch field is permitted. QUANT_CORE_INTEGRATION_ENABLED
remains FALSE operationally because no integration caller exists.
