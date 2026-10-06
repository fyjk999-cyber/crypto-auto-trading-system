# Final acceptance / soak harness

Read-only with respect to strategy behavior.

Run once against the canonical PAPER runtime:

    python3 scripts/acceptance/final_acceptance.py --runtime-url http://127.0.0.1:8010 --db /private/tmp/lr2-soak2/data/crypto_trader.db --root . --expected-sha <candidate-sha>

Sample continuously for a soak:

    python3 scripts/acceptance/final_acceptance.py --runtime-url http://127.0.0.1:8010 --db <paper.db> --root . --expected-sha <sha> --samples 100 --interval-seconds 60

Outputs, under `data/acceptance/` by default:

- `baseline.json`
- `service_topology.json`
- `provider_diagnostics.json`
- `soak_samples.ndjson`
- `p0_events.ndjson` when P0 events are detected
- `test_receipt.json`

The harness only performs HTTP GET and read-only SQLite access. It never places
or cancels orders, forces signals, changes parameters/thresholds, promotes
models, fabricates evidence, or enables LIVE.

## Integrated engineering / future observer binding

The commands above are historical harness examples, not authorization to run a
new acceptance window. Production LowRisk is currently deliberately disabled
and unloaded; integrated engineering must not enable/restart it. The temporary
DB example is not a durable production deployment target.

After a separate controlled cutover review, a **new**, exact-SHA-bound observer
must call `final_acceptance.order_violation(metadata, mode, status)` for order
metadata classification instead of copying the old observer's handwritten
`EXIT/REDUCE/CLOSE` strings. This function consumes canonical Chief enum members
and `execution.exit_evidence.DETERMINISTIC_EXIT_AUTHORITIES`. A Base Exit's
reason is configurable text; its verified authority remains `ACTIVE_BASE_EXIT`.
The old observer script/history must not be rewritten or used as new credit.

This is only a metadata boundary check, not proof of durable exit provenance,
settlement completion, episode completeness, or a natural lifecycle. Those need
independent factual audit/Risk/order/fill/ledger links through the application
resolver and an entirely new qualification and continuous >=72h acceptance.
Missing operational evidence, invalid runtime health, sampler gaps or restarts
cannot be repaired by this classifier. No fake LLM exit record is permitted.
