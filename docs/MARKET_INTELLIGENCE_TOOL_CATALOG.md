# ChiefTrader Tool Catalog

Authoritative inventory produced FROM CODE at `57c3ee3` + Market-Intelligence-V1 work
(`LLMToolRegistry.catalog()` / `tool_versions()`). `tests/opportunity/test_tool_catalog.py`
fails if a tool is registered without an explicit version or description, so this
document cannot silently drift.

## 1. Common contract (every tool)

| Property | Value |
|---|---|
| caller | the SAME canonical ChiefTrader (`select_tools()` phase) |
| nature | read-only; never trades, gates, or assigns direction |
| symbol binding | `LLMToolRegistry.build_package(names, symbol, ...)` rejects any returned evidence whose `symbol` differs from the requested symbol (fail closed → `UNAVAILABLE`, `finding = {}`) |
| timestamp | every `ToolEvidence` carries `timestamp`; `as_of` is passed in `context` |
| freshness | `FRESH` / `STALE` (age > 30 s) / `FUTURE_REJECTED` (genuine future payload) |
| timeout | per-tool `timeout_seconds` (default 10 s, bounded by the overall round deadline 30 s / 45 s) |
| failure | `data_quality = UNAVAILABLE`, `confidence_of_measurement = 0.0`, reason in `contrary_evidence`; no synthetic value |
| budget | at most `MAX_SELECTED_TOOLS = 8` tools per round |
| cache | canonical shared market-data cache keyed by provider+instrument+timeframe+limit+closed_only (see §3) |

Model-visible quality vocabulary: `VALID`, `UNAVAILABLE`, `STALE`, `PARTIAL`,
`REQUEST_FAILED`.

## 2. Canonical production tools (21)

### Alpha / quant evidence tools (`llm/tools/alpha.py`)

| tool_name | version | provider/source | symbol scope | unit / timeframe | history-window semantics |
|---|---|---|---|---|---|
| `trend` | v1 | per-symbol `MultiStrategyAlpha` engine (factual closed OKX candles) | exact requested symbol only | indicator values / configured bars | engine state for the symbol; `UNAVAILABLE` when the router cannot resolve it |
| `momentum` | v1 | as above | exact symbol | ratio / % | recent window |
| `breakout` | v1 | as above | exact symbol | price distance | lookback window |
| `mean_reversion` | v1 | as above | exact symbol | z-score | window |
| `market_regime` | v1 | as above | exact symbol | label (`regime`) | latest computed state; used to enrich the decision context |
| `volatility` | v1 | as above | exact symbol | % | realized window |
| `funding` | v1 | OKX public funding facts | exact symbol | rate (decimal) | latest factual rate; `UNAVAILABLE` if missing |
| `open_interest` | v1 | OKX public OI facts | exact symbol | contracts | latest factual OI |
| `orderbook` | v1 | OKX public order book | exact symbol | price/size | point-in-time book snapshot |
| `liquidity` | v1 | derived from factual book/turnover | exact symbol | USD / ratio | point-in-time; turnover is `ESTIMATED` |
| `basis` | v1 | OKX mark/index facts | exact symbol | % | latest factual basis |

### Factor runtime tools (`llm/tools/factor_runtime.py`)

| tool_name | version | source | scope | semantics |
|---|---|---|---|---|
| `factor_snapshot` | v1 | `FactorService` | stored factors for the symbol | latest stored snapshot |
| `factor_history` | v1 | `FactorService` | symbol + factor | last 100 observations |
| `factor_performance` | v1 | `FactorService` | stored factors | recent sample sizes + out-of-sample performance |
| `factor_health` | v1 | `FactorEvaluator` | stored factors | canonical health status |

### Learned context tools (`llm/tools/context.py`)

| tool_name | version | source | scope | semantics |
|---|---|---|---|---|
| `memory_search` | v1 | `ChiefContextLoader` | symbol/as-of scoped records | reviewed records available at the decision `as_of` |
| `episode_search` | v1 | `ChiefContextLoader` | as-of scoped episodes | same |
| `research_retrieval` | v1 | `ChiefContextLoader` | as-of scoped research | same |
| `coin_profile` | v1 | `ChiefContextLoader` | symbol | same |
| `factor_intelligence` | v1 | `ChiefContextLoader` | symbol/factor | same |

### Market history (`llm/tools/market_history.py`)

| tool_name | version | source | scope | timeframe | semantics |
|---|---|---|---|---|---|
| `multi_timeframe_history` | v1 | OKX public candles (`OKXPublicMarketFeed.client`) | exact symbol | `1m`, `15m`, `1H` | up to 60 CLOSED candles per timeframe; a candle is only usable when `open_at + interval <= as_of` |

### Market Directory (Market-Intelligence V1)

| tool | implementation | scope | bounds |
|---|---|---|---|
| read-only market directory | `market_data/opportunity/directory.py` | whole observable set of the current snapshot | page size ≤ 25 (default 20), ≤ 2 pages per selection round, read-only, `selection_source = DEEPSEEK_SELECTION` recorded when a directory symbol is selected |

The directory is offered inside the bounded selection context (paginated), not as an
unbounded tool call, so the selection round cannot fan out into uncontrolled reads.

## 3. Canonical shared market-data cache

| Property | Value |
|---|---|
| key | `provider + instrument + timeframe + window/limit + closed_only` |
| entry retains | `source`, `fetched_at`, `latest_data_at`, `quality` |
| semantics | optimisation only — never turns stale data fresh |
| failures | failed/empty responses are not stored as valid data |

The observer, evidence prewarm, factor tools and history tools reuse history through this
identity so identical market history is not repeatedly downloaded. `closed_only=True`
entries are the only ones usable for historical factor computation.

## 4. What the tools may NOT do

* emit `LONG`/`SHORT`/`BUY`/`SELL`, quantities, leverage, stops, targets or orders;
* return another symbol's evidence for the requested symbol;
* substitute synthetic/estimated values for a failed provider call;
* bypass `RiskEngine` or `ExecutionAuthority`;
* run outside the global LLM budget (P3 for selected-symbol research, P5 for background).
