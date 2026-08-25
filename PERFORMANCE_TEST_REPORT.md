# PERFORMANCE TEST REPORT

- 100/300 symbol scan not executed in this harness environment.
- Unit-level performance assertions: pytest 347 passed within ~39s.
- Queue backlog, duplicate jobs, lock contention covered by idempotent jobs
  and supervisor tests.
- Full load/soak test remains external operational work.
