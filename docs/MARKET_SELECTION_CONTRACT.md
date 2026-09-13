# Market Selection Contract

Implemented in `src/crypto_trader/market_data/opportunity/selection.py`, persisted by
`selection_store.py` (table `market_selections`), triggered by
`TradingEngine._market_selection_loop`.

Selection is **research-attention authority only**. It is the same canonical
`ChiefTraderEngine` that later calls `select_tools()` and `decide()`.

## 1. Candidate pool (`pool.py`)

Hard cap: **30 symbols**, deduplicated, composed as:

| Category | Cap | Reason label |
|---|---|---|
| factor candidates (non-expired) | 10 | `factor candidate` |
| fair-rotation markets | 10 | `fair rotation` |
| active / anomaly markets | 10 | `large absolute move`, `active turnover`, `funding anomaly` |
| fill (if < 30) | remaining | `oldest-unresearched fallback` |

Symbols already holding a position are excluded. Each pool entry carries compact facts
(last price, 24h move, estimated turnover + quality, funding + quality, OI + quality,
ticker quality, eligibility, research clocks) so the reason is auditable. No category
grants trading authority.

Fairness: rotation uses the independent deep-analysis clock (`last_analysis_at`), and the
fill uses the LLM-research clock (`last_llm_research_at`). Persistent hot factor
candidates cannot starve non-factor markets because the factor category is capped.

## 1b. Two-phase exploration (ChiefTrader-controlled)

Phase 1 sees ONLY the bounded initial pool. The contract allows exactly three
outcomes:

```
SELECT            0-3 symbols from the pool
NO_RESEARCH       explicit, no research this round
REQUEST_DIRECTORY ask the system to run ONE bounded read-only directory lookup
```

If and only if the ChiefTrader returns `REQUEST_DIRECTORY`:

1. the system executes the requested structural query through the read-only
   directory layer (bounded to <=2 pages of <=25 rows, no URLs, no shell, no
   private data);
2. the SAME ChiefTrader receives the directory result in a second, TERMINAL
   phase and must return `SELECT` (0-3 symbols) or `NO_RESEARCH`.

A second `REQUEST_DIRECTORY` is `INVALID_OUTPUT` with
`error_code = NO_THIRD_EXPLORATION_PHASE`; there is no third phase in V1 and no
recursive browsing. A second model call is a second P4 budget acquisition — if
no P4 capacity remains, exploration fails closed (`DEFERRED` /
`SKIPPED_BUDGET`) and position review is unaffected.

Directory provenance is persisted per selected symbol, so the system can always
answer "was this supplied in the initial pool, or did the ChiefTrader discover
it?":

```json
{
  "symbol": "ZECUSDT",
  "from_initial_pool": false,
  "discovered_via_directory": true,
  "directory_query_ref": "market_directory_query:<scan_id>:sort=abs_move|page=1",
  "directory_page_ref": "market_directory:<scan_id>:page=2",
  "selection_source": "DEEPSEEK_SELECTION"
}
```

Pool-native selections carry `from_initial_pool=true` /
`discovered_via_directory=false` and NO directory refs.

## 2. Selection context (bounded)

```
scan_id, snapshot_age_seconds, snapshot_status, snapshot_expires_at, universe_type,
market_set_counts, candidate_pool[], candidate_pool_size, broad_market_summary,
data_quality_summary, existing_positions, execution_supported_label,
global_llm_budget, selection_cooldown_remaining_seconds, last_selection,
market_directory{pages[<=2], note}, authority_note, output_contract
```

No uncontrolled full histories. No secrets. No chain-of-thought.

## 3. Output contract (strict)

```json
{
  "selection_state": "SELECT | NO_RESEARCH | REQUEST_DIRECTORY",
  "selected_symbols": [
    {
      "symbol": "ETHUSDT",
      "brief_reason": "short factual reason",
      "requested_additional_data": ["..."]
    }
  ],
  "directory_query": {
    "sort": "estimated_turnover | abs_move | symbol",
    "page": 1,
    "min_abs_move_pct": null,
    "min_estimated_turnover": null,
    "funding_side": "positive | negative | any"
  }
}
```

`directory_query` is only valid with `REQUEST_DIRECTORY`; its fields are a closed
structural set (unknown keys such as `url` are rejected).

Validation (`pydantic` `extra="forbid"` **plus** an explicit authority-leak scan):

* maximum **3** selected symbols; `NO_RESEARCH` requires zero symbols; `SELECTED`
  requires at least one; duplicates rejected; unknown symbols rejected;
* `brief_reason` bounded to 240 chars; `requested_additional_data` bounded to 5 entries;
* the runtime owns `selection_id` and `scan_id` (model-supplied values are overwritten).

Rejected forbidden fields (recursive, any depth):

```
LONG SHORT BUY SELL action direction side quantity size position_size
position_size_request requested_exposure exposure leverage leverage_request
stop_loss stop take_profit target order_type entry entry_plan exit signal
trade notional risk
```

A leak returns `INVALID_OUTPUT` with `error_code = AUTHORITY_LEAK:<path>`; nothing is
persisted as a selection.

## 4. Lifecycle guards

| Guard | Behaviour |
|---|---|
| no snapshot | `STALE_SCAN` / `NO_SNAPSHOT` |
| snapshot FAILED | `STALE_SCAN` / `SNAPSHOT_FAILED` |
| snapshot expired (>180 s) | `STALE_SCAN` / `SNAPSHOT_EXPIRED` |
| same `scan_id` already selected | returns the existing record; the model is not called again |
| cooldown (300 s default) not elapsed | `DEFERRED` / `SELECTION_COOLDOWN_ACTIVE` |
| empty research pool | `FAILED` / `EMPTY_RESEARCH_POOL` (never a silent `NO_RESEARCH`) |
| budget exhausted for P4 | `SKIPPED_BUDGET` / `LLM_BUDGET_RESERVED_FOR_HIGHER_PRIORITY` |
| provider error | `LLM_UNAVAILABLE`; observation and position management continue |
| provider timeout | `TIMEOUT` |

The duplicate guard survives restart: `MarketSelectionStore.restore_duplicate_guard()`
rehydrates it from `market_selections` at bootstrap.

## 4b. Token optimisation

Phase 1 no longer preloads directory pages, and the snapshot summaries are
trimmed to the attention-allocation facts (pool entries + quality/coverage
counts). Directory data is fetched only when the ChiefTrader asks for it. Live
phase-1 usage is reported by `tools/qualify_market_intelligence_v1.py`; no
mandatory threshold is asserted because provider token accounting is not exact.

## 5. Market Directory (read-only)

`MarketDirectory` lets the model inspect markets outside the 30-symbol pool:

* paginated, page size capped at **25** (default 20), maximum **2 pages per round**,
  bounded total rows, `read_only: true`;
* fields: symbol, instrument identity, last price, 24h move, estimated turnover +
  quality, funding + quality, OI + quality, last observed/analyzed/researched times,
  `execution_supported`, ticker quality;
* query refs are stored on the selection record (`directory_query_refs`).

A symbol discovered through this path and selected is recorded with
`selection_source = DEEPSEEK_SELECTION` and `pool_reasons = ["market directory"]`,
activating the pre-existing `DEEPSEEK_SELECTION` concept in the real runtime path.

## 6. Persistence (`market_selections`)

```
selection_id (PK), scan_id, provider, model, prompt_version,
requested_at, completed_at, candidate_set_ref, directory_query_refs_json,
selected_symbols_json, selection_source, selection_state, status, error_code,
input_tokens, output_tokens, latency_ms, snapshot_age_seconds, created_at
```

Hidden chain-of-thought is never stored. Migration: `0041_market_selection`
(down_revision `0040_runtime_settings`); it also adds `scan_id` / `selection_id` lineage
columns to `llm_decisions`.

## 6b. Downstream authority

`LiveLLMDecisionStrategy.desired_symbol()` → `_selected_research_queue()` only.
When MarketSelection is enabled there is **no** fallback to
`OpportunityBoard.next_agenda_symbol()`: `NO_RESEARCH`, selection failure
(`LLM_UNAVAILABLE` / `TIMEOUT` / `FAILED`), budget deferral
(`SKIPPED_BUDGET` / `DEFERRED`), stale/expired selections, `scan_id` mismatch and
an exhausted selection queue all yield `None` (no new autonomous research).
The board agenda is legacy mode only (`selection_service is None`).

End-to-end: `TradingEngine.tick()` honours the same rule. A scheduled strategy
whose `desired_symbol()` returns `None` (or raises) is SKIPPED — the engine does
not build a context and does not call `on_market_data`, so no default symbol can
be substituted. Position review continues independently.

Directory page semantics: `DirectoryQuery.page` is factual — a lookup starts at
the requested page and returns at most the hard cap of 2 consecutive pages
(page size <= 25), never silently re-serving page 1.

## 7. Downstream consumption

`LiveLLMDecisionStrategy`:

1. prefers symbols from the latest usable selection (the research queue) before routine
   board rotation;
2. refuses selections whose snapshot expired (research continuation stops);
3. passes `deepseek_selected=True` into the opportunity context;
4. records `scan_id` / `selection_id` / `selection_source` lineage on every decision;
5. advances `last_llm_research_at` for the researched symbol.

Direction is still decided only by the final `ChiefTraderEngine.decide()` phase;
RiskEngine and ExecutionAuthority remain downstream and unchanged.
