# Derived ML analytics storage

This directory is DERIVED analytics/research data. It is never canonical trading truth.
The canonical trading source of truth remains the existing persistence layer.

Layout (created by the macOS wrappers):

- `scan_dataset.db` - factual scan snapshots and maturity-gated labels
- `registry.json` - immutable model version registry
- `state.json` / `trainer_heartbeat.json` - trainer state
- `collector_heartbeat.json` - collector counters
- `datasets/` - immutable frozen dataset manifests
- `models/` - immutable model artifacts
- `shadow/` - shadow predictions (no order/risk/sizing authority)
- `logs/` - service logs
