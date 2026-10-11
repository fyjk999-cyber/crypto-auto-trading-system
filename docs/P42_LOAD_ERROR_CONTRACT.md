# Proposed load-error contract

Status: REVIEW_PENDING; historical valid-schema population not captured. Both pinned actual loads still default/mkdir as reproduced. No production repair.

Mutually exclusive result order: IO ENOENT -> CHECKPOINT_MISSING; other IO/permission failure -> CHECKPOINT_UNREADABLE; encoding/JSON/duplicate/non-finite failure -> CHECKPOINT_CORRUPT; valid JSON with unsupported explicitly declared format -> CHECKPOINT_VERSION_UNSUPPORTED; wrong root/known mandatory field type/identity -> CHECKPOINT_SCHEMA_INVALID; otherwise approved legacy envelope with unknown preserved keys -> CHECKPOINT_VALID. Ordering is explicit; no invalid file can be classified missing. Unknown keys alone are not invalid or a fabricated schema version.

Reading never mkdirs or creates sidecars. Do not inject defaults into malformed or unreadable documents. MISSING may initialize only through an approved writer CREATE operation under ownership/CAS. API/stats read-only loads must report missing/unavailable, not initialize. Historical schema acceptance must be agreed from source plus later authorized factual capture; proposed tests on made-up schemas are not population proof.

Caller behavior changes must be implemented together in a later stage:

- CLI: surface typed error and nonzero exit; no fallback fresh task or automatic repair.
- Engine/backfill/incremental: reject the task before fetch/write. Broad exception handling must NOT invoke ordinary mark_error on an invalid/unreadable/unsupported base. Preserve original failure separately; leave CP untouched.
- Maintenance/background: keep resolution UNKNOWN/BLOCKED, do not count defaults as backlog/eligible work; other unrelated tasks follow an explicitly reviewed isolation policy, not implicit continuation.
- API/stats/discovery: publish typed unavailable/error counters without fake coverage/freshness; do not trigger a writer, create directories or repeatedly parse protected historical data.
- Recovery/retention: no delete/reset/default initialization as a response to load error.

Version/identity/schema mismatch must be quarantined logically, not moved or copied without maintenance authority. Cursor/origin/restored keys with unknown history remain preserved and conservatively block incompatible writes. Known corrupt behavior changes intentionally; it is not backward-compatible success. Old consumers that require default dictionaries need explicit adaptation and regression before implementation admission.

Tests: every category, permission versus absence, missing read no directory, old approved legacy document preserved, unknown fields, bad known types, bool masquerading numeric, duplicate/nonfinite, caller error not swallowed, no fetch/mark_error after invalid load.
