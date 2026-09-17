# Low-Risk P1 Closure Receipt

Recorded: 2026-09-17T01:56:37Z

## P1-2 cron-49 retirement evidence (before removal)

- id: `cron-49`
- schedule: `10 0 * * *` (Asia/Shanghai)
- target cwd: `/Users/huhongjie/Documents/ChatGPT/crypto-low-risk-v2`
- runtime reference in prompt: `http://127.0.0.1:8010`, DB
  `/tmp/lr2-soak2/data/crypto_trader.db`, SHA `1ef721d6d491`
- lifecycle authority: the prompt instructed running Growth jobs against the live
  acceptance runtime and said "do not restart it unless dead", i.e. it could start
  the non-launchd `/tmp/lr2-soak2` runtime.
- action: retired with the scheduled-task API (`cron_remove cron-49`); no runtime
  start/restart/kickstart authority remains.
- other scheduled tasks reviewed: `cron-34` is a paused read-only watchdog that
  explicitly forbids restarts; `cron-35` belongs to turbo-100. Neither owns the
  Low-Risk PAPER runtime.

## P1-3 startup-path classification

- `scripts/run_low_risk_paper_secure.sh` = CANONICAL_RUNTIME_ENTRY
- `scripts/deepseek-keychain.sh run` = MANUAL_WRAPPER_ONLY
- `scripts/start-paper.sh` = MANUAL_WRAPPER_ONLY
- `scripts/start-ai-fund-manager.sh` = MANUAL_WRAPPER_ONLY
- `scripts/start-local-system.sh` = DEV_UI_ONLY / NOT_RUNTIME_OWNER
- direct `python -m crypto_trader.runtime.local_runner` = UNSUPERVISED_DEV_ONLY /
  NOT_CANONICAL

Canonical ownership remains `com.lowrisk.paper` only.

## P1-4 model policy

- `TRADING_LLM_MODEL=deepseek-flash` is the only allowed production trading model.
- `deepseek-v4-pro` and `deepseek-flash-high` are denied by policy and fail closed.
- Generic `LLM_MODEL` can never override an explicit `TRADING_LLM_MODEL`.

## P1-5 promotion status semantics

This repository's promotion primitive is `crypto_trader.evolution.promotion.EvolutionPromoter`.
It only promotes when `BACKTEST_PASS`, `OOS_PASS`, `WALK_FORWARD_PASS` and
`SHADOW_PASS` are all present.

- PROMOTION_POLICY = EVIDENCE_GATED
- PROMOTION_PIPELINE_AVAILABLE = YES (library primitive present, not auto-activated)
- CURRENT_ELIGIBLE_CHALLENGER = NO
- `REAL_PROMOTION_GATE` is not used by this Low-Risk runtime as an eligibility
  signal, and no text in this repository implies a challenger is cleared to promote.
