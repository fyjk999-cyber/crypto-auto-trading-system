# P4.2 independent review record — partial source closure

Spec reviewer: /root/p3_spec. Standards reviewer: /root/p3_standards. Review fixed point 630533f2349d5a4d9f4033384a7044e6c3055250. Reviews performed independently, no production access.

## Initial rejected version

Exact 59b8694cf356a07b686ff7703ea6a82e4658c65c: both REQUEST_CHANGES. Numeric JSON 1e999 overflow was accepted as CHECKPOINT_VALID despite the non-finite contract. Spec also found the permission test replaced the reader itself rather than faulting the fixture file-open boundary, so it did not test the actual reader's fallback. These findings remain historical facts, not erased by a successor.

## Successor Spec

Exact 5d8698e5c8415ab57629f86c5e0f489526f79bf7: PASS_CONTRACT_ONLY. Independent scoped retest 25 passed. Positive/negative nested exponent overflow now corrupt; permission fault leaves actual reader handling intact and demonstrates completed document appearing fresh/default while original bytes stay unchanged. Proposed ownership/raw CAS/load/durability/retry contracts conservative, not production repair.

Full readiness: BLOCKED_INSUFFICIENT_SOURCE. Known routes still require complete receiver/caller certification and route-specific retry/error evidence. P4_2_SOURCE_AND_CONTRACT_READY = NO. Historical provenance/T1/custody and production defects not accepted.

## Successor Standards

Same exact successor: PASS_CONTRACT_ONLY. Independent focused retest 27 passed in 2.67s. No remaining actionable safety/Standards findings in corrections/proposed contracts. Initial history retained. Full source readiness remains NO due to internal receiver/caller and route-specific semantic gaps. Combined suite and production not independently checked.

These are saved faithful review summaries, not authenticated external custody or raw transport transcripts. No review grants implementation, deployment, service operation, T1, PAPER or soak authority. The producer source is unchanged.
