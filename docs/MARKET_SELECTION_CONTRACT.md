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
  "selection_state": "SELECTED | NO_RESEARCH",
  "selected_symbols": [
    {
      "symbol": "ETHUSDT",
      "brief_reason": "short factual reason",
      "requested_additional_data": ["..."]
    }
  ]
}
```

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
