# OPEN PR DISPOSITION (PHASE 3 - INITIAL FORENSIC PASS)

- AUDIT_UTC: 2026-09-17T10:02:00Z
- LANDING_BASE: d8ca1fd071288558dca237e57db83fa947be4896 (spec freeze; parent 19b97849...)
- PR refs fetched as refs/remotes/origin/pr/*
- No PR was merged or closed.

| PR | Head | Merge base with landing | Unique commits vs landing | Initial disposition |
|---|---|---:|---:|---|
| #2 | 72e10e63d9860ce87c634d3fbd348040f36eed98 | fc244d470cad1536085834c4f77ae47b2688cb6a | 160 | PARTIAL - unique correctness behavior likely still needed |
| #3 | b3873d015b40916066dc19243e7d005be5ae3f5b | fc244d470cad1536085834c4f77ae47b2688cb6a | 196 | SUPERSEDED_WITH_EVIDENCE candidate - final Growth branch already integrated |
| #4 | 46c91fc44e63dd72615f4e52b73c2a31336efc77 | fc244d470cad1536085834c4f77ae47b2688cb6a | 160+ | PORT_REQUIRED - growth publication/knowledge semantics appear absent in final tree |
| #5 | 9144c9887157c6ef6f1ccd14f538bec1b2ea6e4d | fc244d470cad1536085834c4f77ae47b2688cb6a | 160+ | NEEDS_DUPLICATE_STACK_AUDIT - quarantine proposal not yet proven superseded |

## PR #2 checklist against final landing tree

| Required behavior | Current final landing evidence | Initial status |
|---|---|---|
| wall-clock Chief/tool budget | no wall_clock / tool_budget / deadline budget in src | PORT_REQUIRED |
| OKX SWAP volume semantics | market_data/opportunity/service.py uses vol24h + volCcy24h and derives USD turnover | SUPERSEDED / ALREADY_PRESENT |
| exact-symbol episode retrieval | review scheduler and episode queries exist; exact-symbol scope still needs targeted proof | NEEDS_EVIDENCE |
| research applicability fail-closed | no explicit applicability gate found | PORT_REQUIRED |
| tool contract versioning | no tool_contract / versioned contract persistence found | PORT_REQUIRED |
| execution-cost evidence semantics | decision-time costs exist in snapshot evidence; tool evidence route needs targeted check | NEEDS_EVIDENCE |
| OPEN-position review priority | position manager exists but no explicit open-position priority queue found | PORT_REQUIRED |
| bounded concurrency | no bounded concurrency limiter found | PORT_REQUIRED |
| review deadline | position_manager cooldown exists, no review deadline found | PORT_REQUIRED |

Relevant PR #2 commits identified for port review:

- 7ecbb33 - enforce tool timeout and bounded tool budget in registry
- 4215e5c - expose sources, timing and execution-cost evidence
- d05be1c - persist versioned selection contracts
- c227816 - prioritize and bound open-position reviews
- 0aa4489 - fail closed on unscoped legacy knowledge
- 1514b97 - close deadline, volume and scope gaps

## PR #3 Growth V2 convergence

The final landing tree already contains the accepted Growth / Memory branch:

- 01c58a3a1ead1827a09660bbcef10da0a21a9196 is an ancestor of the landing base.
- Growth is LEARNING_ONLY, is_order=false, can_modify_core=false.
- Worker heartbeat and derived DB are active in the factual baseline.

Status: SUPERSEDED_WITH_EVIDENCE pending final migration/tree comparison of PR #3's migration files. No old Growth migration lineage will be imported.

## PR #4 checklist against final landing tree

| Required behavior | Current final landing evidence | Initial status |
|---|---|---|
| fenced atomic knowledge publication | no fenced/publication fence found | PORT_REQUIRED |
| exact job input/revision binding | no job/revision binding found | PORT_REQUIRED |
| attempt recovery | Growth worker retry exists; exact attempt recovery semantics need proof | NEEDS_EVIDENCE |
| NO_PUBLISH_INPUT behavior | no NO_PUBLISH_INPUT found | PORT_REQUIRED |
| durable provider exceptions | provider exception handling exists but not this exact growth contract | NEEDS_EVIDENCE |
| latest visible version handling | growth_memory_versions table exists; latest-visible semantics need proof | NEEDS_EVIDENCE |
| revoke/expire known_at correctness | no known_at found in Growth knowledge path | PORT_REQUIRED |
| proposition identity | no proposition identity found | PORT_REQUIRED |
| real DB import target binding | no import-target binding found | PORT_REQUIRED |
| authorized rollback | ML rollback exists; Growth knowledge rollback path absent | PORT_REQUIRED |
| resume source/plan identity | no resume source/plan identity found | PORT_REQUIRED |
| scoped retrieval fail-closed | no scoped fail-closed retrieval found | PORT_REQUIRED |
| hard serialized evidence budget | no Growth serialized evidence budget found | PORT_REQUIRED |
| canonical V2 trace path | Growth trace reporting exists but needs canonical V2 path proof | NEEDS_EVIDENCE |
| evidence taxonomy | final review taxonomy exists (review_taxonomy.py) | SUPERSEDED / ALREADY_PRESENT |

Relevant PR #4 commits must be audited in detail before any closure. This is currently the largest open PR port risk.

## PR #5 duplicate-stack audit

Initial static findings:

- One canonical runtime entrypoint exists in the landing branch: src/crypto_trader/runtime/bootstrap.py::build_system.
- Legacy modules from earlier architectures still exist in the tree and should be checked for import smoke / accidental use:
  - src/crypto_trader/ai_brain/
  - src/crypto_trader/capital_deployment/
  - src/crypto_trader/demo/
  - src/crypto_trader/deepseek/
  - older factor/evolution modules
- No duplicate local_runner bootstrap was found in the final landing tree at first pass.
- A dedicated import-smoke and active-use test matrix is required before marking PR #5 SUPERSEDED.

Status: NEEDS_DUPLICATE_STACK_AUDIT.

## Closure rule

No open PR may be considered closed until:

1. every unique required behavior is either ported to the landing branch or shown superseded by exact final-tree code/tests;
2. the disposition is recorded here;
3. the PR is explicitly classified PORTED, SUPERSEDED, or REJECTED_WITH_REASON.


## Round 2 disposition update

### PR #2

`PARTIALLY_PORTED` on final landing tree:

- wall-clock tool-round budget: PORTED in `ToolDrivenChiefTrader`
- tool timeout: PORTED in `LLMToolRegistry.call` / `build_package`
- tool contract versioning: PORTED via `ToolContract` and `contract_catalog`
- OKX SWAP volume semantics: ALREADY_PRESENT in opportunity service
- research applicability fail-closed: PORTED via scoped/as-of research retrieval
  and `0043_research_scope`
- OPEN-position review priority: still open (PORT_REQUIRED)
- bounded concurrency: still open (PORT_REQUIRED)
- explicit review deadline: still open (PORT_REQUIRED)
- execution-cost evidence semantics: still needs final targeted proof

### PR #3

`SUPERSEDED_WITH_EVIDENCE`: final Growth branch architecture is integrated;
Growth remains `LEARNING_ONLY` with no order path and its own worker/memory
versioning.

### PR #4

`PARTIALLY_PORTED` on final landing tree:

- fenced atomic publication: PORTED/EQUIVALENT via DB unique version fence and
  single-transaction immutable version insert; duplicate-version test added
- exact job input/revision binding: PORTED via `_meta.input_hash` + revision
- NO_PUBLISH_INPUT: PORTED via explicit `GrowthPublishInputMissing`
- latest visible version handling: PORTED in `GrowthRetriever.search`
- proposition identity: PORTED via deterministic `proposition_identity`
- known_at correctness: PORTED via `_meta.known_at`; expiry/revocation filters
- scoped retrieval fail-closed: PORTED via strict symbol scope
- hard serialized evidence budget: PORTED via `max_serialized_bytes`
- evidence taxonomy: ALREADY_PRESENT in final review taxonomy
- attempt recovery: worker cycle state/cursor/heartbeat already restart-safe;
  targeted regression evidence still to be attached
- durable provider exceptions: provider durability suite already covers
  fail-closed provider exceptions
- canonical V2 trace path: still open (PORT_REQUIRED)
- real DB import target binding: still open (PORT_REQUIRED)
- authorized Growth rollback: still open (PORT_REQUIRED)
- resume source/plan identity: still open (PORT_REQUIRED)
- revoke/expire known_at: ported for version visibility; admin revocation
  workflow still open

No PR is closed yet.

### PR #5

`NEEDS_DUPLICATE_STACK_AUDIT`: final import-smoke/active-use matrix still
required before any quarantine or supersession decision.
