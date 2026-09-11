# Attribution and evolution (G12)

Only the Daily Review / low-frequency path may call
`AdaptiveCardStore.apply()` or `DailyCardLearner.learn_day()`.  The learner
rejects `origin != "DAILY_REVIEW"` with `PermissionError`.

## Attribution axes

Each factual outcome is split into:

| Axis | Source | Notes |
| --- | --- | --- |
| `market_outcome` | factual net PnL | descriptive only (`WIN/LOSS/BREAKEVEN`) |
| `decision_quality` | structured review availability | `PARTIAL/UNKNOWN` |
| `prediction_correctness` | review evidence refs | `SUPPORTED_ASSOCIATION` / `CONTRADICTED` / `UNKNOWN` |
| `risk_adjustment` | episode leverage presence | `PARTIAL/UNKNOWN` |
| `execution_quality` | fill lineage presence | `PROVEN/UNKNOWN` |
| `data_quality` | funding/coverage provenance | `PROVEN/UNKNOWN` |
| `external_unmodeled` | review data gaps | `UNKNOWN` by default |

Causality is always recorded as `OUTCOME_ASSOCIATED`.  `CAUSALLY_PROVEN`
raises at construction.  A WIN does not increment every used card; a LOSS
does not invalidate a card.

## Operation semantics

| Operation | Meaning | Version effect |
| --- | --- | --- |
| `KEEP` | used card but no new relevant evidence, or card not used | same version + journal revalidation event |
| `UPDATE` | new support or contradiction for the same trigger/context | version + 1 |
| `CREATE` | no compatible card; needs repeatability, recognizable trigger, future relevance, factual evidence | version 1, status CANDIDATE unless independent sample criteria met |
| `SPLIT` | old card mixed two contexts with different guidance | parent RETIRED (version +1), children created with `supersedes_rule_id/version` |
| `MERGE` | triggers, context and guidance compatible | target updated; sources RETIRED; sources recorded in rationale and source ids |
| `WATCH` | contradiction or unresolved evidence | version +1, status WATCH |
| `RETIRE` | policy/manual retirement; legacy preserved | version +1, status RETIRED |

A single episode can never create an `ACTIVE` card: `assess_card_quality`
requires `min_samples_for_active` (default 3), complete trigger, known regime,
repeatability/evidence thresholds and a contradiction-rate ceiling.
MERGE refuses conflicting guidance instead of averaging it.

## Version answers

For any card the system can answer:

* current version (canonical row);
* previous versions and their snapshots (`growth_card_versions`);
* why a version was produced (`operation`, `update_reason`, `proposal_hash`);
* which episodes caused it (`source_episode_ids_json`);
* which decision used which version (`growth_card_decision_traces`).

`KEEP` reuses the current version with a unique `proposal_hash`; replay after
restart is idempotent.  `UPDATE/WATCH/RETIRE/SPLIT/MERGE` append a new
snapshot; nothing is overwritten or deleted.

Tests: `tests/growth_system_v2/test_attribution_evolution.py`,
`test_closed_loop_g14.py`, `test_read_write_separation.py`.
