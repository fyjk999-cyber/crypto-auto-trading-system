# SAFE UPGRADE POLICY

- Validated candidate -> READY_FOR_UPGRADE -> WAIT_SAFE_WINDOW.
- Safe window requires no open positions/orders/pending execution, low trade
  frequency, non-extreme volatility, healthy market/exchange/reconciliation,
  kill switch off.
- Activation pauses NEW ENTRY only; risk/exit/reconciliation keep running.
- Failure => rollback and record UpgradeFailureExperience.
