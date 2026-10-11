# P4 candidate admission contracts — not adopted

## G1R_T1_CAPTURE_ADMISSION_PLAN

The executable `preflight_plan` checks completeness of supplied fixture booleans;
it does not authenticate evidence or authorize capture, even if all are true.
Production admission needs an independently reviewed, hash-bound record for each:

1. CURRENT_INVENTORY of the entire canonical checkpoint tree and actual full
   schema; old T0_MANIFEST_493 is historical and cannot replace it.
2. Exact raw bytes/full-key canonical objects, types/unknowns/source/origin,
   path/inode/mtime, source and release SHA, cutoff and UTC capture clocks.
3. Current process identity/start/owner and exclusive maintenance ownership;
   unique lock holder verified without competing write/lock probes.
4. Active consumers and proven fail-closed behavior during maintenance; no Turbo
   operation or production reads in P4. If not proved, block the stop window.
5. Separately authorized stop/resume path, two whole-tree reads with equal raw
   hashes, zero unaccounted files or competing writes, preservation of original
   bytes and independent reviewer custody.
6. Per-entry disposition including unresolved origin, paused, deferred, unknown,
   malformed and drift; no blanket PASS. No provider availability inferred.
7. Approved rollback, first natural post-resume cycle and independent gates;
   no maintenance interval earns soak credit.

Production maximum files/bytes/memory/maintenance time = UNKNOWN. Historic
493-file timings are not measurements of today's full tree. A future approved
plan must establish hard limits before stop, preflight resource fit and abort
on inventory growth, budget exhaustion, unknown keys, identity drift, race,
hash failure, consumer unsafe state or rollback uncertainty. Capture into an
exclusive new evidence directory, publish a complete manifest only after all
checks; partial capture remains INVALID, retained for audit. No automatic retry
or producer resume can erase failure. All actual execution remains NOT_RUN.

## Independent custody candidate

Use P3 Evidence V2 content validation unchanged. Immutable snapshots append only,
mutable task pointer separately monotonic; preserve legacy ledger mismatch.
Producer submits exact source/receipt/test hashes and parent ID, declared UTC and
verifier version. A separately authorized reviewer authenticates source and
submission using a distinct execution principal and an external trustworthy
anchor recording content/parent/review result and actual receipt time. Caller
booleans, differing numeric UID values and same-UID agents are not proof.

Reviewer may read approved frozen artifacts, not edit producer evidence. Producer
cannot modify retained external acceptance; storage administrators cannot silently
rewrite history. Retain all versions, rejected submissions, access audit and
revocations; never delete inconsistent old evidence. ACL/role/principal/anchor
implementation needs separate authorization and is NOT performed here.

Future verifier validates chain/schema/content with pinned verifier; independently
authenticates principal, anchor and monotonic receipt ordering; checks replay and
cross-version binding, missing objects and unapproved updates. Missing/unverifiable
anchor or identity blocks formal acceptance. On outage or disaster restore exact
bytes from approved replicas, compare anchor, quarantine divergence, retain failure;
new recovery baseline requires separate approval, never repairs old T0 trust.

`CUSTODY_DESIGN = COMPLETE_CANDIDATE`
`FORWARD_CONTENT_INTEGRITY = PASS_LOCAL_CONTENT_ONLY` (P3 frozen evidence)
`INDEPENDENT_CUSTODY = NOT_ESTABLISHED`
`FORMAL_EVIDENCE_GATE = BLOCKED`

## P4_GATE_AMENDMENT_REVIEW_RECEIPT

Original SPAC base 48101858512fa6c78e568691519058f5f8843bbf;
remote Addendum f22e589b38935e0c34fea11fe6807475c7284f92;
expected SHA256 f4a1e933b385a1e62ee8dcd7fee0c64fd71eea4494883218a0a249a99c6a9079.
Original Addendum is retained, not repushed. This separate candidate clause is:

G1 original stays BLOCKED, waiver NO, T0 equivalence NOT_PROVABLE. Replacement
slot may become PASS_BY_AUTHORIZED_REPLAN only after real complete T1, all G1-R
subgates and authenticated independent custody accepted. Every production read,
maintenance, mutation and service transition still needs its own exact authorization.
Documentation and fixture PASS do not satisfy production gates or retrospectively
change G1/G2. `amendment_candidate` refuses missing gate inputs and never adopts
the amendment even with complete fixture inputs. G2 old budget remains FAIL.

`GATE_AMENDMENT = CANDIDATE_ONLY`; authoritative SPAC was not changed.

## G1R_CAS_CRASH_FIXTURE_RECEIPT

`FixtureCAS` can only create its own temporary laboratory; no production path
argument. Whole-object unknown/control/origin preservation, exact raw CAS,
strict successor revision, advisory exclusive fake lock, temp file fsync, replace,
directory fsync and exact post-read. Retry of already committed bytes still syncs
directory, with failure propagated. Synthetic fixture_note is not a production
metadata exclusion. Pending temp after injected crash is not a committed record.

Tests model competing FDs, drift, stale revision, duplicate JSON, control corruption,
before/after-rename crash and idempotent retry. They do not simulate power loss,
authenticate real process principals, or defend against noncooperating writers.
Original Order 2d T1/manifest prerequisites remain unmet: formal acceptance BLOCKED.
