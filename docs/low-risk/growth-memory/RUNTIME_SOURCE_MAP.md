# Runtime Source Map (K0)

- ML_SCAN_SOURCE_DB: `/Users/huhongjie/lowrisk-ml/data/ml/scan_dataset.db`
- ML_SCAN_ROWS: 750 (verified read-only on 2026-09-16; collector pid 46360 running)
- TRADING_SOURCE_DB: `/tmp/lr2-soak3/data/crypto_trader.db` (most recent canonical PAPER DB)
- TRADING_SOURCE_ACTIVE: NO (no trading runtime process running; historical snapshot only)
- GROWTH_DERIVED_DB: `<growth runtime>/data/growth/growth.db` (Growth-owned, read/write)
- SOURCE_WRITE_POLICY: source DBs opened read-only (`mode=ro`); Growth writes only its derived DB; source facts never mutated
- ML service command line confirms collector argv DB = ML_SCAN_SOURCE_DB
