# RUNTIME R0 RECOVERY AUDIT

## Accepted facts
- CODE_HEAD == RUNNING_SHA == c385795a413b7363ce1f0220fb5c5d6113009a4d
- DB migration head = 0027_trade_plan_decision_unique
- trade_plans exists
- decision_id uniqueness active
- ACTIVE_RUNTIME_COUNT = 1
- EXECUTION_WRITER_COUNT = 1
- EXECUTION_LEASE_COUNT = 1
- /health = OK
- /ready = PAPER ready
- /runtime = RUNNING
- ENTRY_ORDERS_WITHOUT_TRADEPLAN = 0
- ENTRY_FILLS_WITHOUT_TRADEPLAN = 0
- ENTRY_FILLS_WITH_TRADEPLAN = 28 (post-deploy)

## R0 recovery event
- Prior stale runtime PID 17965 had lease expired after host sleep (~43h).
- Kill Switch engaged correctly as fail-safe.
- Stale runtime terminated; DB backed up.
- One controlled cold start performed (PID 55645, run_767a83591078458fab251c955b633c37).
- No restart loops.

## Lease health
- Historical lease contradiction root cause: NOT_REPRODUCED_ON_CLEAN_COLD_START (R0)
- Later reproduced: host sleep caused lease expiry -> kill switch.
- Post-recovery cold start lease internally consistent (health.execution_lease=true, /runtime.lease_held=true).
