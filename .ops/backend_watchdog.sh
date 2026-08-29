#!/bin/bash
# DEPRECATED (2026-08-29): previous watchdog did a blind `DELETE FROM
# runtime_leases` on health failure — violates lease invariants
# (health failure != runtime dead; supervisor must never mutate leases).
# Canonical liveness owner: .ops/backend_supervisor.sh
exit 0
