# FACTOR DATABASE

Tables (migration 0004_factor):
- factor_registry(factor_id, name, version, status, description)
- factor_values(symbol, factor, timeframe, value, confidence, metadata_json)
- factor_snapshots(symbol, timeframe, snapshot_json)
