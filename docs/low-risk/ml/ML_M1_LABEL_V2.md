# M1 - LABEL-V2 EXACT FACTUAL MATURER

- SPEC_SHA: a4bf252fdde093eb322974c4aba1dd4e1c0a5e1c
- Branch: codex/low-risk-ml-final-scientific-closure
- BASE_SHA: fa63877cafac (M0)
- MODE: LEARNING_ONLY; label-v1 preserved and excluded.

## Implemented

- New module src/crypto_trader/ml_labels.py:
  - label identity label_version=label-v2, horizons 1m/5m/15m/30m/1h/4h;
  - target_ts = T0 + horizon; endpoint = last CLOSED candle whose close time is <= target;
  - strict no-lookahead: candles with close_ts > target never contribute high/low/close;
  - persisted audit fields: requested_target_ts, actual_target_ts, alignment_error_seconds,
    endpoint_policy, path_start_ts, path_end_ts, data_gap, factual_source, entry_price,
    future_high, future_low, realized_volatility, gross/net bps, cost_version,
    cost_components_json, maturation_status, usable_for_training, label_config_version;
  - statuses IMMATURE / MATURE_VALID / INCONCLUSIVE_DATA_GAP / INCONCLUSIVE_ALIGNMENT /
    TRANSIENT_SOURCE_ERROR; only MATURE_VALID is usable_for_training;
  - versioned economics: decision-time snapshot costs when present, otherwise explicit
    label-cost-v2-fallback-estimate with quality=estimated_missing (no bare universal 22);
  - mature_pending is idempotent per (snapshot_id, horizon, label_version), retries transient
    rows, and marks snapshot LABELED only when all six horizons are MATURE_VALID.
- OKX historical pagination:
  - OKXAdapter.get_history_candles (public /api/v5/market/history-candles, no credentials);
  - OkxHistoricalCandleProvider with bounded pages (max_pages), newest-first backward
    pagination, closed-candle filter, timestamp de-duplication, chronological sort and a
    window-aware cache.
- Schema: migration 0032_ml_label_v2_fields adds all audit columns additively/nullable;
  verified upgrade 0031 -> 0032 on a fresh temp DB.
- Collector wiring: scripts/ml_collector.py now matures label-v2 through the provider and
  no longer uses wake-time ticker price or writes label-v1.
- Readiness gate tightened: final_label_count requires label-v2 + MATURE_VALID +
  usable_for_training; freeze_dataset selects only those rows; label-v1-only returns NO_LABEL_V2.

## Tests / evidence

- tests/low_risk/test_ml_label_v2.py: 5 tests - exact horizon, post-horizon spike cannot change
  label, data gap, alignment, transient retry + duplicate idempotency, cost versioning,
  >300-bar pagination with unconfirmed rows dropped and cache reuse.
- Updated tests/low_risk/test_ml_collector.py to assert label-v2 maturity/idempotency and the
  absence of the old wake-price label path.
- Focused ML suite: 34 passed; ruff clean; alembic head 0032_ml_label_v2_fields.
- No runtime service, Growth line, DB row, artifact or label-v1 row was modified.

## Next

- M2: wire factual decision-time #01-#24 expert evidence into scanner snapshots
  (candidate/control same schema, no #25 self-input), then M3 #21 immutable dataset training.
