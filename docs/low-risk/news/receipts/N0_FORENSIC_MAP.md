# N0 FORENSIC ARCHITECTURE MAP (NEWS / EXTERNAL EVIDENCE)

Status: ACCEPTED - CHECKPOINT N0
Spec SHA: 3caf879b622e2eccd55045900f566cf8bfe02d5e
Implementation branch: codex/low-risk-news-external-evidence-final-closure
Implementation starting SHA: 3caf879b622e2eccd55045900f566cf8bfe02d5e
Worktree: isolated git worktree at /Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system
Spec: docs/low-risk/news/NEWS_EXTERNAL_EVIDENCE_FINAL_CLOSURE_SPEC.md
Python: 3.12, SQLAlchemy 2.x async, SQLite/aiosqlite, Alembic, pytest asyncio

Baseline test collection (spec SHA, isolated worktree):
- pytest tests/low_risk -q --collect-only -> 291 collected
- pytest tests -q --collect-only -> 948 collected
- ruff check src scripts tests -> All checks passed

No invasive News coding was performed before this map was written.

---

## 1. Existing Research / Evidence Infrastructure

### 1.1 src/crypto_trader/research/

| File | Canonical object | Current role | Classification |
|---|---|---|---|
| anomaly_detector.py | AnomalyEvent, AnomalyDetector.detect() | in-memory market anomaly descriptors | KEEP (not News) |
| consensus.py | ResearchConsensus, ResearchConsensusEngine.consensus() | aggregates research conclusions | KEEP; not NewsEvent source corroboration |
| experiment_planner.py | ExperimentPlan, ExperimentPlanner | research experiment planning | KEEP |
| hypothesis_agent.py | ResearchHypothesis, HypothesisAgent.generate() | derived hypotheses | KEEP |
| market_researcher.py | MarketResearchReport, MarketResearcher.research() | derived market research | KEEP |
| priority.py | ResearchPriority, ResearchPriorityEngine | research ranking | KEEP |
| ranking.py | ResearchPriority, ResearchRanker | generic evidence ranking | EXTEND concept only; News ranking has different inputs |
| regime_detector.py | RegimeResult, RegimeIntelligence.classify() | market regime classification | KEEP |

Decision: the existing research/ package is generated/derived research. It must remain distinct from factual News ingestion. It will not be the canonical store or parser for RawNewsItem / NewsEvent.

### 1.2 src/crypto_trader/research_agents/

- models.py: AgentReport, ResearchConsensus - KEEP.
- supervisor.py: ResearchSupervisor - KEEP.
- factor_agent.py, market_agent.py, risk_agent.py: agent report producers - KEEP.
- consensus.py: ResearchConsensusEngine - KEEP.

### 1.3 src/crypto_trader/ai_research_lab/lab.py

AIResearchLab and ResearchReport produce generated research. KEEP; not the canonical News pipeline.

### 1.4 src/crypto_trader/llm/tools/

- registry.py: ToolEvidence, EvidenceItem, DynamicEvidencePackage, LLMToolRegistry.register/call/build_package. Canonical read-only evidence tool seam. EXTEND with a news_context evidence tool.
- context.py: register_context_tools(loader, tools) currently registers memory_search, episode_search, research_retrieval, coin_profile, factor_intelligence, growth_memory. EXTEND with news_context.
- alpha.py: build_canonical_tool_registry(). KEEP.
- research_agents.py, research_feedback.py: generated research tools. KEEP; not factual News.

### 1.5 Chief context

- src/crypto_trader/llm_chief/context.py
  - ChiefTraderContext dataclass fields: symbol, market_snapshot, regime, quant_evidence, portfolio_state, risk_summary, position_state, position_context, knowledge, similar_episodes, coin_profile, compressed_experience, failure_warnings, memory_refs, state_version, research_refs, episode_refs, pattern_refs, opportunity_context, model_evidence, prepared_at.
  - estimate_tokens() includes bounded context fields. EXTEND with news_context and include it in token estimate.
- src/crypto_trader/llm_chief/context_loader.py
  - ChiefContextLoader.enrich() loads reviewed factual memory/research and Growth retrieval into context.
  - load_tool() maps tool names to loaders; _growth_retrieval_evidence() is the canonical Growth as-of loader. EXTEND with a NewsRetriever-backed as-of news context and a news_context tool.
- src/crypto_trader/llm_chief/engine.py
  - ChiefTraderEngine.render_prompt() renders market/quant/25-model/portfolio/position/knowledge/Growth/opportunity blocks into the Core-LLM prompt.
  - select_tools() / decide() are the existing two-stage path. EXTEND with a bounded, explicitly untrusted NewsEvidence block.
- src/crypto_trader/llm_chief/tool_orchestrator.py
  - ToolDrivenChiefTrader.decide() selects tools and builds DynamicEvidencePackage. KEEP; News must not create a second decision engine.
- src/crypto_trader/llm_chief/decision_store.py
  - LLMDecisionStore.save() persists LLMDecisionORM including memory_refs_json, episode_refs_json, research_refs_json, tool refs, opportunity lineage. EXTEND with exact News refs via canonical news_decision_refs persistence.
- src/crypto_trader/llm_chief/runtime_strategy.py
  - LiveLLMDecisionStrategy.build_chief_context() and on_market_data() are the canonical flat/new-direction path. enrich() is the News context insertion seam; decisions.save(...) is the exact lineage seam.
- src/crypto_trader/llm_chief/position_manager.py
  - LiveLLMPositionManager.review() is the canonical OPEN-position path: context build, evidence package, Core LLM call, then existing signal translation. Deterministic protection is evaluated before review in TradingEngine. EXTEND with news_context and optional forced wake, never a replacement path.
- src/crypto_trader/llm_chief/invocation.py
  - MaterialEvent; MATERIAL_EVENT_KINDS already includes MAJOR_NEWS.
  - ReassessmentInvocationManager deduplicates per leg, allows one active reassessment, and queues newer events. ADAPT as the canonical dedup/staleness gate for News-triggered reassessments.
- src/crypto_trader/llm_chief/reassessment.py
  - ReassessmentEvaluator, ReassessmentWake; evaluate PRICE/TIME/INDICATOR/EVENT wake conditions only. KEEP.

### 1.6 Canonical runtime / reassessment path

- src/crypto_trader/runtime/engine.py
  - TradingEngine.tick() is the canonical per-tick loop.
  - OPEN-position section computes deterministic exits first (_deterministic_exit_signals), then calls self.position_manager.review(ctx, position, force=wake_required), then process_signal(...).
  - _position_state_version(position, plan) binds decision freshness to plan version, quantity, and position updated_at.
  - process_signal() routes approved signals through Risk / ExecutionAuthority; News must not bypass it.
  - offline_mode, llm_router, ExecutionAuthority unchanged. EXTEND tick() with an optional News reassessment claim/force around the existing position_manager.review() call. No second loop.
- src/crypto_trader/runtime/event_bus.py: EventBus.subscribe/publish/subscriber_count. KEEP.
- src/crypto_trader/runtime/scheduler.py: IntervalScheduler(interval_seconds, callback).start()/stop(). KEEP.
- src/crypto_trader/runtime/supervisor.py: TradingRuntimeSupervisor supervises trading loops; unsuitable for external provider ingestion. KEEP.
- src/crypto_trader/operating_system/jobs.py: JobScheduler.run_once(). KEEP.
- src/crypto_trader/governance/scheduler.py: DailyReviewScheduler.loop(). KEEP.
- src/crypto_trader/learning/growth_worker.py: GrowthWorker.run_once() with heartbeat/state JSON. ADAPT as pattern for a dedicated News worker.
- scripts/growth_worker.py, scripts/run_growth_macos.sh, deploy/launchagents/com.lowrisk.growth.plist: user-level launchd pattern; ADAPT as pattern for com.lowrisk.news. Never modify or restart Growth/ML services.

### 1.7 State version / staleness

- ChiefTraderContext.state_version is populated by LiveLLMDecisionStrategy._fresh_state_version() from clock, mark, and portfolio quantities.
- LiveLLMPositionManager.review() persists exact position snapshots; stale output is handled by canonical state-version semantics.
- LLMResponse.state_version / CoreLLMRouter carry version metadata.
- News must use this exact mechanism; no new staleness logic.

### 1.8 Audit / observability / API

- src/crypto_trader/observability/audit.py: AuditService.log(...). EXTEND with News actions; redact secrets.
- src/crypto_trader/api/app.py: FastAPI app factory with read-only routes including GET /growth/status and GET /llm/decisions. EXTEND with read-only /news/* routes.
- src/crypto_trader/api/deps.py: AppState. EXTEND only if needed; News API may instantiate a read-only repository from state.database.session_factory.
- src/crypto_trader/growth_status.py: read-only status builder pattern. ADAPT as pattern for news/status.py.

### 1.9 Persistence / migrations

- src/crypto_trader/persistence/models.py: single declarative Base.
- Existing potentially reusable tables: research_reports (generated research), llm_decisions (decision lineage), audit_events (audit trail), growth_memory_versions (Growth retrieval only).
- Current Alembic head: migrations/versions/0040_growth_memory_versions.py.
- Database.init_schema() uses Base.metadata.create_all in tests; Alembic is the deployment path.
- Decision: ADD a canonical News table family. No existing table can host raw provider truth, immutable event versions, evidence versions, provider cursors, decision refs, and outcome reviews without semantic corruption. Migration 0041+ will create only new tables; no destructive change to existing tables.

### 1.10 Growth / retrieval seam

- src/crypto_trader/learning/retrieval.py (GrowthRetriever) and src/crypto_trader/llm_chief/growth_context.py are the accepted Growth retrieval mechanism.
- News lineage is additive/read-only. The deployed Growth runtime is not modified or restarted. News will expose news_decision_refs and news_outcome_reviews for later Growth review.

---

## 2. Classification Matrix

| Capability | Verdict | Exact seam / action |
|---|---|---|
| Research framework | KEEP | research/, research_agents/, ai_research_lab/ remain derived research |
| Research LLM tools | KEEP | llm/tools/research_agents.py, research_feedback.py remain generated evidence |
| News ingestion | ADD | new crypto_trader/news/providers/ + worker.py |
| RawNewsItem | ADD | immutable raw model + news_raw_items |
| NewsEvent | ADD | event/version model + news_events, news_event_versions |
| NewsEvidence | ADD | bounded evidence model + news_evidence |
| Provider adapters | ADD | NewsProvider base, OKX official announcements, RSS feed provider |
| Source profiles | ADD | versioned source policy + news_source_profiles |
| Dedup / syndication | ADD | news/dedup.py, news_event_items relation classification |
| Event clustering | ADD | news/clustering.py with versioned policy constants |
| Entity mapping | ADD | news/entities.py, news_entity_links |
| Freshness | ADD | versioned per-event policy in news/materiality.py |
| Materiality | ADD | versioned engine in news/materiality.py, immutable news_evidence snapshots |
| Core LLM context | EXTEND | ChiefTraderContext.news_context, ChiefContextLoader, ChiefTraderEngine.render_prompt |
| Reassessment | EXTEND | MaterialEvent(kind=MAJOR_NEWS) + canonical ReassessmentInvocationManager + TradingEngine.tick |
| Persistence | EXTEND | append ORM tables + Alembic 0041+ |
| API | EXTEND | add /news/status, /news/events, /news/events/{id} read-only |
| Growth lineage | KEEP / ADD hooks | no Growth service change; news_decision_refs, news_outcome_reviews |
| Worker / scheduler | ADD (justified) | dedicated user-level com.lowrisk.news launchd worker, because no existing canonical component provides isolated external HTTP polling/provider failure isolation without touching the production trading runtime |
| EventBus | KEEP | available but not required for durable provider cursors |
| AuditService | EXTEND | News actions use existing service with redacted payloads |
| ML collector/trainer | KEEP | untouched; no News in historical ML rows |
| Growth runtime | KEEP | untouched and never restarted by this mission |

---

## 3. Selected Architecture

    providers (OKX official / RSS feed / fake fixture)
      -> RawNewsItem (immutable ingestion truth)
      -> normalization + hashes
      -> layered duplicate/syndication classifier
      -> NewsEvent version cluster (immutable event versions)
      -> entity/symbol links with confidence and ambiguity
      -> versioned source profile
      -> taxonomy + fact/claim class
      -> novelty + freshness + direction + contradiction
      -> versioned materiality engine
      -> bounded immutable NewsEvidence
      -> SQL persistence (News-owned tables in canonical migration chain)
      -> optional NewsReassessmentRequest (WAKE-UP ONLY)
      -> canonical TradingEngine.tick -> ReassessmentInvocationManager dedup
      -> LiveLLMPositionManager.review(force=True)
      -> existing Core LLM -> existing TradePlan -> Risk -> ExecutionAuthority

Dedicated News worker:
- scripts/news_worker.py, scripts/run_news_macos.sh, deploy/launchagents/com.lowrisk.news.plist.
- Durable absolute paths; no /tmp canonical state; heartbeat/state JSON; bounded cycles; graceful SIGINT/SIGTERM; no trade/order authority.
- Isolated News DB path (data/news/news.db) using the same canonical Alembic migration chain. Documented reason: the production/final PAPER trading DB must not be altered by this mission; provider ingestion has a separate failure domain. Final convergence runs the same migrations against the canonical DB.
- No exchange credentials.

Flat/open behavior:
- Open position: News request may add force=True to the existing LiveLLMPositionManager.review() call in TradingEngine.tick.
- Flat: News request is recorded and canonical opportunity review continues; News never emits OPEN and never bypasses LiveLLMDecisionStrategy.

As-of contract:
- NewsRetriever.get_news_context(symbol, as_of, position_state, max_items, token_budget) filters NewsEvidence.available_at <= as_of, NewsEventVersion.available_at <= as_of, and excludes evidence with expires_at <= as_of.
- ChiefTraderContext.news_context carries exact evidence refs; LLMDecisionStore persists them to news_decision_refs.

Safety boundaries:
- NEWS_ORDER_AUTHORITY = NO
- NEWS_NEW_RISK_AUTHORITY = NO
- NEWS_EXIT_AUTHORITY = NO
- External text is sanitized and bounded before prompt insertion; it is never concatenated as system/developer instruction.

---

## 4. N1-N10 Execution Plan

| Checkpoint | Deliverable | Focused tests |
|---|---|---|
| N1 | Domain models, ORM tables, migration 0041+, repository gateway | migration + round-trip + provider state |
| N2 | Provider ABC, OKX announcements, RSS provider, cursor/retry/isolation | parse, idempotency, cursor recovery, provider failure |
| N3 | Normalization, layered dedup, event versions, corrections/retractions | duplicate/syndication/update/correction tests |
| N4 | Entity/symbol mapping, ambiguity, broad relevance, taxonomy, source profiles | direct asset, ambiguous ticker, exchange/macro |
| N5 | Novelty, freshness, direction, contradiction, materiality, NewsEvidence builder | freshness/expiry, materiality tiers, noise suppression |
| N6 | news_context tool + as-of retrieval + bounded context + prompt-injection boundary + decision refs | as-of, bounded, support/counter, injection, decision refs |
| N7 | Canonical reassessment request/dedup/stale integration + open-position priority + flat safe | dedup, stale, risk/exit authority, no-order proof |
| N8 | Outcome review service, Growth lineage, /news/status, /news/events, metrics | API, lineage, outcome review |
| N9 | Dedicated autonomous worker, launchd, heartbeat, restart-safe cursors, backpressure | worker cycle, restart, provider down, burst bound |
| N10 | Fresh focused/news, low-risk, full suite, Ruff, detached exact-SHA acceptance, factual runtime receipt | all above |

---

## 5. Existing Test Baseline and Suites

- News tests to be added under tests/news/.
- Existing low-risk regression suite: pytest tests/low_risk -q.
- Full suite: pytest tests -q.
- Ruff: ruff check src scripts tests.
- Exact-SHA detached acceptance uses a separate clean worktree at the pushed checkpoint SHA.

---

## 6. No-Write Findings Record

At N0:
- No production runtime process was started.
- No Growth or ML service was stopped, restarted, or modified.
- No LIVE trading path was enabled.
- No News file was written outside this isolated worktree and the N0 receipt.
