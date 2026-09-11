# Safety boundaries (non-negotiable)

## 1. ChiefTrader authority

Experience Cards are evidence/context only.  The tool output has
`evidence_only=true`, `can_emit_direction=false` and no action field.  Cards
never produce `LONG/SHORT/BUY/SELL/EXIT/ORDER`; the final direction authority
remains the existing ChiefTrader / Live LLM.  The integration test
`test_chief_card_integration.py` asserts the Chief decides `NO_TRADE` while
receiving cards, and that cards cannot emit a direction.

## 2. Risk immutable

V2 modules never import or mutate `crypto_trader.risk`.  Card operations do
not change kill switch, leverage limits, sizing, approve/scale-down/reject
authority or execution safety gates.  `test_invariants.py` checks the module
import graph and that `RiskEngine` configuration is unchanged after card
operations.

## 3. Execution immutable

V2 modules never import `execution`, `order`, `exchange`, `simulator` or
`runtime`; no order submit, fill creation or position mutation exists in the
card code.  `test_invariants.py` asserts no `OrderORM`/`FillORM` rows are
created by card operations, and `test_chief_card_integration.py` asserts a
Chief decision with cards creates no order/fill.

## 4. Factual-only learning

Cards are created/updated only from:

* canonical factual episodes (`trade_episodes`, complete CLOSED lifecycle);
* structured reviews persisted by the v1 pipeline with evidence refs;
* versioned decision traces that prove which card version was used.

No fake episode, fake fill, forced trade, synthetic evidence or test fixture
may be promoted to a production card.  Tests use throwaway temp DBs and the
conftest refuses known runtime/production paths.

## 5. Read/write separation

* Runtime: `ExperienceCardRetriever` and `register_experience_card_tool` are
  read-only.  A statement listener test proves no INSERT/UPDATE/DELETE.
* Daily Review: `AdaptiveCardStore` / `DailyCardLearner` may write, gated by
  the existing day claim/fence (`fence` false → `ClaimLostError`, no write).
* `CardDecisionTraceStore` writes only the trace journal.

## 6. No hidden black box

Retrieval always returns excluded reasons, score components, policy version
and card versions.  No semantic similarity can bypass the hard filter.

## 7. No forbidden scope

Not implemented and explicitly out of scope: Skill Genome, new vector/graph
database, agent swarm, per-factor autonomous skill generation, self-editing
production code/prompts during live trading, automatic strategy code
generation, automatic Risk mutation.

## 8. Runtime authorization

`RUNTIME_AUTHORIZED = false`, `DEPLOYED = false`.  This engineering package
does not start, restart or deploy any trading runtime.
