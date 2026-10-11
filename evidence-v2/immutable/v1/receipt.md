# P3A forward baseline V1 — new observation, not historical reconciliation

Source code commit749c0d4bf995fb04db0cb2ea43514e2dbb3e3e58 is pinned separately
from any later commit containing this baseline's evidence files. Baseline time is
2026-10-11T14:11:32Z. Current production facts were not collected for this baseline:
UNKNOWN. The new baseline does not assert original T0 state or accept any old Gate.

The legacy immutable citation prefix69a087f50c320221 does not match the retained
ledger hash8777e17a7154f45285070bc5160fe9ba2030038dff15aff07a27528f0d088fa6.
Original bytes remain NOT_RECOVERED. All original ledger/citation/receipts are
untouched. New mutable progress is kept outside historical evidence files.

The source implements offline forward manifest/hash/version checks; return values
always preserve LEGACY_EVIDENCE=FAIL_MISMATCH, INDEPENDENT_CUSTODY=NOT_ESTABLISHED
and FORMAL_EVIDENCE_GATE=BLOCKED, even if a same-UID rewritten chain is consistent.
New manifests refer to immutable local artifact bytes and exact source commit.
They cannot be trusted as independent external custody merely by hashing themselves.

Static KB publication preserves all nine source files and24 models at fixedff73e0c.
It has no Chief/registry/training/monitor wiring. Offline comparison is disabled by
default and labels supplied facts unverified; missing facts remain NOT_AVAILABLE.
Data-read prototype and fake WAL backup tests carry no production admission.

This baseline is frozen before independent review. Review is PENDING at this
version's creation. Later reviewer records are separate attestations, not edits to
these frozen bytes. Production/PAPER/qualification/soak acceptance is not granted.
