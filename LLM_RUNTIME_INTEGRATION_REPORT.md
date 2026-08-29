# Phase 8D-1.5 LLM Provider Runtime Integration Report

Date: 2026-08-28

## Scope and result

One canonical `LLMGateway` is shared by the three existing brains. It supports
OpenAI, DeepSeek and custom OpenAI-compatible endpoints; configures providers
and six semantic model routes at runtime; encrypts local secrets outside the
database; records safe usage metadata; and exposes a real provider test and
manual route qualification path.

The local runtime deliberately remains PAPER-only. `LIVE_TRADING_ENABLED=false`
was preserved. The provider runtime has not been given a real API key, so no
external provider request was made during this delivery.

## Domain model layer

`DeepSeek / deepseek-chat` is now explicitly presented as a Base Model, while
`CryptoTrader-Live-v1`, `CryptoTrader-Learning-v1`, and
`CryptoTrader-Evolution-v1` are versioned reasoning profiles. The frontend
displays the two levels separately. Domain profiles use the same LLMGateway and
record their version into DecisionEvidence-capable data; they do not create a
provider-specific trading model or a fourth Brain.

## Three-brain status

```text
╔════════════════════════════════════════╗
║ 1. LIVE TRADING BRAIN                  ║
╠════════════════════════════════════════╣
║ LLM Gateway                  ✅ COMPLETE ║
║ Live Analysis Route          ✅ COMPLETE ║
║ Structured Output            ✅ COMPLETE ║
║ RiskEngine Boundary          ✅ COMPLETE ║
║ ExecutionAuthority Boundary  ✅ COMPLETE ║
║ LLM Failure → No New Entry   ✅ COMPLETE ║
║ Exit/Risk remain alive       ✅ COMPLETE ║
╚════════════════════════════════════════╝
╔════════════════════════════════════════╗
║ 2. DAILY LEARNING BRAIN                ║
╠════════════════════════════════════════╣
║ LLM Review Route             ✅ COMPLETE ║
║ Lesson Route                 ✅ COMPLETE ║
║ Retryable Failure            ✅ COMPLETE ║
║ Memory Commit Integrity      ✅ COMPLETE ║
╚════════════════════════════════════════╝
╔════════════════════════════════════════╗
║ 3. EVOLUTION BRAIN                     ║
╠════════════════════════════════════════╣
║ Research Route               ✅ COMPLETE ║
║ Hypothesis Route             ✅ COMPLETE ║
║ Candidate Reasoning Route    ✅ COMPLETE ║
║ Protected Core Isolation     ✅ COMPLETE ║
║ Champion unchanged on fail   ✅ COMPLETE ║
╚════════════════════════════════════════╝
```

## Validation evidence

- Database migration: `0016_llm_runtime (head)` applied successfully.
- Full backend suite: `647 passed, 7 skipped`.
- Lint: `ruff check .` passed.
- New/changed formatting scope: passed. Repository-wide `ruff format --check .`
  still reports 22 existing unformatted files outside this phase; no broad
  formatting rewrite was applied to avoid unrelated churn.
- Frontend: `21` tests passed, type check passed, production build passed.
- Agent project suite: passed (`75` code, `56` integration with `4` skips,
  `22` regression, `9` SPAC checks).
- Browser: `http://127.0.0.1:5173/#/llm` verified with NOT_CONFIGURED status,
  password key field, six route labels, and both action controls.
- Unconfigured Live runtime: verified after restart that usage counts stay
  stable; it does not repeatedly invoke an unknown LLM route.

## Truthful qualification state

```text
PHASE_8D1_5_LLM_RUNTIME_INTEGRATION_COMPLETE = YES
LLM_RUNTIME_CONFIGURATION_READY = YES
LLM_PROVIDER_RUNTIME_VALIDATED = NOT_RUN
24H_SOAK_VALIDATED = NO
PAPER_CLOSED_LOOP_RUNTIME_READY = NO
REAL_MONEY_READY = NO
```

To progress, configure a provider at `#/llm`, use **测试连接**, save the provider
and routes, then run `./scripts/llm_runtime_qualification.sh`. Do not start a
24-hour soak before the script returns `LLM_PROVIDER_RUNTIME_VALIDATED=YES`.
