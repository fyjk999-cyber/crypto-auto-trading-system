# PHASE 6 RECEIPT - IDENTITY LINEAGE & RECOVERY (LOW-RISK V2 MASTER SPEC)

Status: **PARTIAL** (lineage builder + runtime fill capture COMPLETE; recovery consumption pending)

BASE_SHA: 422ddee7cc7d
FINAL_PHASE_SHA: e4d80bc595d7 (runtime capture); lineage module first landed at 0e8ea9d

## Existing modules inspected (KEEP/EXTEND, no parallel ledger)

- domain/identifiers.py (new_id prefixes), persistence/models.py order/fill/plan/decision columns
  (orders.client_order_id, fills.fill_id, order_events.event_id, ledger_transactions.transaction_id),
  observability/audit.py (AuditService), llm_chief/trade_planner.py + trade_plan/service.py
  (plan/decision ids), market_data/opportunity lineage fields (migration 0023).
- Conclusion: identity links already exist across canonical tables; Phase 6 = deterministic
  assembly/validation + audit persistence, not a new ledger.

## ADD

- runtime/lineage.py: LINEAGE_STAGES (opportunity_id -> decision_id -> position_episode_id ->
  leg_id -> trade_plan_version -> intent_id -> execution_id -> client_order_id ->
  exchange_order_id -> fill_ids), OPTIONAL_STAGES for pure decisions, LineageChain
  (missing/complete/trade_complete), build_lineage, validate_lineage (missing + unexpected keys),
  and lineage_from_order(...) with canonical fallbacks (candidate_source, entry_decision_id,
  trade_episode_id, plan_version, client/exchange order ids).
- runtime/engine.py: every factual _settle_fill now audits FILL_LINEAGE with the validated chain
  (authority LINEAGE_ONLY, is_order=False).

## Tests / evidence

- tests/low_risk/test_phase6_lineage.py (6): full chain completeness; missing exchange/fill links;
  trade-complete without opportunity; unexpected key surfaced; order-metadata fallback mapping;
  end-to-end engine run opens a V2 position and asserts the persisted FILL_LINEAGE payload is
  trade_complete with client-order + fill IDs present.
- Regression at commit: low_risk + bootstrap + live lifecycle -> 193 passed; ruff clean.

## Schema / migrations

No new tables: lineage is assembled from existing columns and persisted in the canonical audit
event stream.

## P0 blockers

None.

## P1 issues

- position_episode_id / leg_id are captured when present in order metadata; runtime population of
  those links for every entry/hedge remains.
- Recovery/restart consumption of lineage (cross-checking local vs exchange identities on restart)
  is not yet wired end-to-end.

## Next

Phase 7: race/authority matrix completion (REST/WS done at 9521cc6, exit V1->V2 done at 09f26c2),
restart-recovery e2e, natural PAPER lifecycle with real OKX + real DeepSeek, >=72h soak.
