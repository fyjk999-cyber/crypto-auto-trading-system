# Adaptive Experience Card schema (G09)

Canonical persistence truth: **`ai_compressed_experience`** (extended in
place).  No second memory table.  Two narrow journals support lineage/trace:

* `growth_card_versions` — append-only version/operation journal;
* `growth_card_decision_traces` — per-decision retrieval audit.

## 1. Canonical table field mapping

| Semantics | Column | Notes |
| --- | --- | --- |
| identity | `rule_id`, `title` | `rule_id` unique, deterministic `card_<sha40>` |
| knowledge | `content`, `guidance_json` | guidance is structured, conditional |
| experience type | `experience_type` | `ADAPTIVE_CARD` for V2; legacy rows become `COMPRESSED_EXPERIENCE` |
| account/mode | `account_id`, `mode` | scope isolation |
| trigger | `trigger_signature_json`, `factor_refs_json` | canonical factor states + definition versions |
| context/scope | `context_signature_json`, `applicability_scope_json` | symbol/instrument/regime/trend/vol/direction/timeframe |
| evidence | `source_episode_ids_json`, `supporting_episode_ids_json`, `contradicting_episode_ids_json` | factual ids only |
| evidence counts | `source_episode_count` (sample), `support_count`, `contradiction_count` | repeated identical import never increases them |
| quality | `confidence`, `quality_score`, `decay_score` | confidence is not win rate; scores from `MemoryGovernor`/`KnowledgeDecayEngine` |
| status | `status` | `CANDIDATE/ACTIVE/WATCH/STALE/RETIRED` |
| lineage | `version`, `supersedes_rule_id`, `supersedes_version`, `update_reason` | current version; history in journal |
| time | `known_at`, `last_validated_at`, `updated_at`, `created_at` | historical queries use `known_at`/journal visibility |
| compatibility | `symbol` | legacy field, used for cross-symbol/fallback rules |

## 2. Version journal

`growth_card_versions` rows have `(card_rule_id, version, operation,
proposal_hash, snapshot_json, source_episode_ids_json, trigger/context
signatures, counts, status, reason, supersedes ids, created_at)`.
`proposal_hash` is unique, which makes a restarted daily review replay
idempotent.  `KEEP` records a revalidation event at the **same** version and
does not create a pointless version.

## 3. Decision trace

`growth_card_decision_traces` records candidate/selected/excluded card refs,
excluded reasons, card versions, retrieval scores, applicability notes,
trigger/context signatures, `as_of` and `decision_id`/`evidence_package_id`.
It is an audit surface, not a second decision store: the decision itself stays
in `LLMDecisionORM` / `DynamicEvidencePackage`.

## 4. Migration

Production migration truth: Alembic revision
`migrations/versions/0040_growth_v2_cards.py`
(`revision=0040_growth_v2_cards`, `down_revision=0039_applicability`).

* fresh DB / previous head → new head: adds the V2 columns in place, creates
  `growth_card_versions` + `growth_card_decision_traces` and the account/mode/
  status/scope indexes;
* legacy rows: backfilled to `experience_type='COMPRESSED_EXPERIENCE'`,
  `status='WATCH'`, `share_scope='ACCOUNT_MODE'`, `known_at=created_at`; data
  is never deleted;
* repeat upgrade: no-op; downgrade removes only V2 columns/journals;
* PostgreSQL offline SQL compilation is tested; a real PostgreSQL run requires
  `GROWTH_V2_POSTGRES_URL` and is otherwise reported NOT_VERIFIED.

`growth_v2_migration.py` is now TEST/SUPPORT only (isolated unit tests that do
not run the complete migration chain).  Tests:
`tests/growth_system_v2/test_alembic_migration.py` and
`test_card_schema_and_migration.py`.

## 5. Backward compatibility

Existing `AICompressedExperienceORM` consumers keep working: original columns
are unchanged.  Legacy rows without trigger/context are only retrievable as
general fallback when the retrieval policy explicitly allows it and are
penalized in ranking; they are never guessed into a specific trigger.
