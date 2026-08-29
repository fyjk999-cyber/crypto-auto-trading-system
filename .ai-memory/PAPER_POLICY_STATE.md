# PAPER POLICY STATE (§61) - NOT the truth source; Settings/DB/runtime win

| Parameter | Current | MIN | DEFAULT | MAX | MAX_CHANGE/30m |
|---|---|---|---|---|---|
| market_observer_candidate_target | 5 (planned) | 3 | 5 | 20 | ±2 |
| deep_analysis_candidate_limit | 5 | 3 | 5 | 12 | ±2 |
| per_symbol_analysis_cooldown_s | 240 | 60 | 240 | 900 | ±60 |
| memory_retrieval_limit | 5 | 3 | 5 | 12 | ±2 |
| history_context_depth | 3 | 1 | 3 | 10 | ±2 |
| research_budget_per_window | 2 | 0 | 2 | 6 | ±1 |
| tool_call_budget_per_decision | 6 | 2 | 6 | 12 | ±2 |
| paper_exploration_probability | 0.10 | 0.0 | 0.10 | 0.30 | ±0.05 |
| paper_exploration_size | 0.0005 | 0.0001 | 0.0005 | 0.001 | ±0.0001 |
| max_paper_concurrent_positions | 8 | 4 | 8 | 16 | ±2 |

Last action: ROLLBACK @ 2026-08-29T22:30Z (staged 300 cancelled; baseline 240 restored before effect).
Rollback = restore prior row values (§64). Small steps only (§83).
