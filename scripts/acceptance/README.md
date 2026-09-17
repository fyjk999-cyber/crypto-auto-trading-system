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
