# DECISIONS

- 2026-08-27T05:11:15.694769+00:00: Only VALIDATED + certified immutable candidates may promote. Safe
  window is deterministic. Health/smoke failure auto-rolls-back. Kill switch
  remains authoritative. Single losing trade never triggers rollback.
