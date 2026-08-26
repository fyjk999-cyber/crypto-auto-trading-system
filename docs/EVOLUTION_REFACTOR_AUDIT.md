# EVOLUTION REFACTOR AUDIT

|Module|Classification|Action|
|-|-|-|
|runtime/engine.py|KEEP|Live trading core; evidence write only|
|risk/|KEEP|Immutable authority|
|execution/|KEEP|Immutable authority|
|order/|KEEP|Immutable lifecycle|
|exchange/|KEEP|Immutable adapters|
|ledger/|KEEP|Single financial truth|
|portfolio/|KEEP|Projection truth|
|market_data/|KEEP|Immutable ingestion|
|reconciliation/|KEEP|Immutable|
|observability/|KEEP|Audit/ops|
|persistence/|KEEP|Durability|
|decision_replay/|ADAPT|Become Evidence SSOT facade|
|governance/daily_review.py|MERGE|Into Evolution review pipeline|
|governance/scheduler.py|MERGE|Into Evolution Review Scheduler|
|governance/memory.py|ADAPT|Behind MemoryGateway|
|governance/memory_persistence.py|ADAPT|Behind MemoryGateway|
|governance/backtest.py|ADAPT|Behind ValidationPipeline|
|governance/walk_forward.py|ADAPT|Behind ValidationPipeline|
|governance/stress.py|ADAPT|Behind ValidationPipeline|
|ai_brain/learning/|ADAPT|Evidence/lesson store via gateway|
|ai_brain/review/|ADAPT|Behind review pipeline|
|learning/|ADAPT|Behind review pipeline|
|learning_coordinator/|DEPRECATE|Merge into Evolution scheduler|
|ai_memory/|ADAPT|Behind MemoryGateway|
|memory_governance/|ADAPT|Behind MemoryGateway|
|memory_graph/|ADAPT|Behind MemoryGateway|
|vector_memory/|ADAPT|Behind MemoryGateway|
|research/|ADAPT|Behind ResearchGateway|
|research_agents/|ADAPT|Behind ResearchGateway|
|strategy_research/|ADAPT|Behind ResearchGateway|
|ai_research_lab/|ADAPT|Behind ResearchGateway|
|ai_optimization/|ADAPT|Proposal only|
|evolution/|KEEP + EXTEND|Canonical evolution core|
|prompt_evolution/|ADAPT|Candidate lineage|
|training_scheduler/|DEPRECATE|Merge into Evolution scheduler|
|validation/|ADAPT|Behind ValidationPipeline|
|validation_engine/|ADAPT|Behind ValidationPipeline|
|ai_certification/|ADAPT|Behind ValidationPipeline|
|shadow/|ADAPT|Behind ValidationPipeline|
|shadow_campaign/|ADAPT|Behind ValidationPipeline|
|strategy_lifecycle/|ADAPT|Evolution state machine|
