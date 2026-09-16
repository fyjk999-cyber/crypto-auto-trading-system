# HEDGE OPERATIONAL EVIDENCE LOG

Factual PAPER observations only; no forced trades, no fabricated fills, no fake LLM output.

- 2026-09-16T12:24:17.629661+00:00 | START | run=8020 | mode=PAPER | live=false | ready=true | lease=held | /health=OK | legs=0 | leg_orders=0 | leg_fills=0 | orders=0 | fills=0 | next=waiting for natural opportunity
- 2026-09-16T12:36:15Z | RUNNING | pid=86812 alive=true | ready=true mode=PAPER live=false lease=held | db: legs=0 leg_orders=0 leg_fills=0 orders=0 fills=0 llm_decisions=1 | natural_two_leg=none | heartbeat=87054 | next=waiting for natural opportunity
- 2026-09-16T12:39:02Z | RUNNING_OFFLINE | pid=86812 alive=true | ready=true mode=PAPER live=false lease=held | /health=UNHEALTHY (llm_offline_mode) | legs=0 orders=0 fills=0 llm_decisions=2 | natural_two_leg=none
- 2026-09-16T12:41:17Z | OFFLINE_WINDOW | router.offline=true since 12:36:05Z reason=INVALID_JSON; next_probe_at=12:41:05Z overdue; engine offline_mode next_probe_at=12:42:09Z | no LLM call is attempted while offline and flat, so router recovery cannot self-trigger on this frozen branch
- 2026-09-16T12:41Z | PRIOR_RUN_FACT | run_ebe34e38a49f4f379d223efb7523c6e1 decision 12:25:01Z reason=LLM_TIMEOUT -> offline; run_a9eebddecc1044d096f3ffc5d55fd11f decision 12:37:09Z reason=INVALID_JSON -> offline. Real DeepSeek Core-LLM decision contract failure, independent of the hedge/leg subsystem (no orders/fills/legs created).

