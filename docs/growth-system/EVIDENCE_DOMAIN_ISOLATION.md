# Evidence Domain Isolation Contract

Status: required architecture constraint (BACKTEST / PAPER / LIVE).

## Domains

```text
execution_mode=BACKTEST  -> evidence_domain=BACKTEST
execution_mode=PAPER     -> evidence_domain=PAPER
execution_mode=LIVE      -> evidence_domain=LIVE
```

BACKTEST is never stored as PAPER.  `validate_domain_mode` fails closed when the
execution mode and evidence domain disagree.

## Namespace isolation

* `EpisodeBinding.evidence_domain` is explicit.
* `pattern_logical_id` includes `evidence_domain`; the same proposition under
  BACKTEST and PAPER produces two different logical pattern IDs.
* lesson/pattern `scope_json` always carries `evidence_domain`.
* card rule identity is namespaced by account/mode/evidence domain.
* compression and pattern aggregation are scoped by account/mode (and domain
  for card identity), so BACKTEST samples cannot raise PAPER sample counts or
  validation state.

## Provenance

BACKTEST publication requires all of:

```text
backtest_run_id, strategy_version, strategy_hash, dataset_hash,
date_range, symbol, timeframe, fee_model, slippage_model, funding_model,
execution_model, parameter_set_hash
```

Missing provenance raises `BacktestProvenanceError` and blocks publication.

## Retrieval

`CardRankingPolicy.allowed_evidence_domains` defaults to the decision's own
domain.  A PAPER decision therefore receives PAPER cards only; BACKTEST cards
require explicit policy permission.  Card evidence carries
`source_evidence_domain` and `runtime_validated` labels; trace payload carries
`decision_evidence_domain` and per-card selected domains.

## Explicitly forbidden

```text
CROSS_DOMAIN_SAMPLE_MERGE        forbidden
CROSS_DOMAIN_CONFIDENCE_MERGE    forbidden
CROSS_DOMAIN_COMPRESSION         forbidden
BACKTEST_TO_PAPER_AUTO_PROMOTION forbidden
BACKTEST_TO_LIVE_AUTO_PROMOTION  forbidden
```

Cross-domain comparison may report divergence; it must not merge state.

## Remaining work

* BT08/BT09/BT13/BT15 depth (cross-domain divergence report, full trace domain
  audit, repeated dataset/run independent-sample identity) still needs
  adversarial coverage.
* The six Round-5 closure findings from the e7d3e88 review remain open and are
  not fixed by this addendum.
