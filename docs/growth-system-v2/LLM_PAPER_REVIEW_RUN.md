# Built-in LLM PAPER review run

Status: **COMPLETED** for the historical factual PAPER episodes.  The harness
did not author any review content; the in-system DeepSeek provider generated
every observation, explanation and lesson below.

## Configuration

```text
provider        = deepseek (macOS Keychain credential, loaded in memory)
model           = deepseek-flash
thinking        = enabled
max_tokens      = 8192
retries         = 2-3 bounded
scheduler       = existing DailyReviewScheduler
runner          = StructuredReviewRunner (provider -> publisher -> card learner)
source facts    = canonical-clean trade_episodes (33 factual CLOSED episodes)
migration       = Alembic 0040_growth_v2_cards + growth metadata create_all
```

## Result

```text
episodes REVIEWED              = 33 / 33
structured attempts (all)      = 53 KNOWN usage
successful structured attempts = 33
generated lessons              = 59 CANDIDATE
generated patterns             = 20 CANDIDATE
adaptive cards                 = 0
compressed experiences         = 0
```

`cards=0` and `compressed=0` are the system's fail-closed result: every
published pattern scope currently has `independent_sample_count=1`, below the
required minimum of 3 independent episodes, so no pattern reached
`VALIDATED`/`CONTESTED` and no card was promoted.

Model lineage: 24 episodes were first reviewed by `deepseek-chat`; after the
operator switched back to flash thinking, the remaining 9 episodes were
reviewed by `deepseek-flash` with the 8192-token cap.  The runtime review
provider is now configured as flash/thinking/8192.

## System-generated lessons (examples, verbatim from `growth_lessons`)

All 59 lessons are `CANDIDATE` (`sample_count=1`):

```text
- When a short is entered on a BEAR regime with negative momentum but
  below-average volume, the entry may be more prone to short-term adverse
  drift than when momentum is volume-confirmed.
- A large gap between requested quantity in the trade plan and realized episode
  quantity indicates the executed position may not reflect the intended thesis,
  so outcome attribution should be treated cautiously.
- With no position_actions recorded during the hold and a terminal EXIT, the
  exit was likely driven by the exit decision rather than an in-trade
  adjustment; reviewing exit-decision rationale is therefore the key lever.
- When the entry regime is RANGE and the directional thesis is based on an
  already-extended 24h move, treat continuation signals as lower-confidence and
  require a range-position check before acting.
- Large simultaneous volume and volatility expansion at entry should be logged
  with directional context (up-bar vs down-bar) so continuation and exhaustion
  interpretations can be separated in post-trade review.
- Mildly negative funding and basis should not be treated as standalone bearish
  confirmation without accompanying positioning data.
- Large gaps between requested and filled quantity should be flagged during
  review because they change the effective exposure.
- When a contrarian mean-reversion long is taken in a RANGE regime against a
  fresh break below prior low, concurrent volume expansion may indicate the
  breakdown has real participation.
```

## Data-integrity boundary

Compared with the pre-run backup, the review run did not change any trading
fact:

```text
trade_episodes=33, orders=205, fills=434,
risk_decisions=3388, llm_decisions=13271, trade_plans=167
```

No order, fill, Risk decision, runtime or production database outside the
target factual DB was modified.  All generated knowledge is candidate-only and
no direction authority was produced.

## Reproduction

```bash
.venv/bin/python scripts/growth_review_worker.py \
  --db <factual-db> \
  --date <YYYY-MM-DD> \
  --model deepseek-flash \
  --thinking \
  --max-tokens 8192
```

The source DB is backed up through the SQLite backup API before any write; the
provider credential is loaded from the project Keychain helper into memory and
is never printed.
