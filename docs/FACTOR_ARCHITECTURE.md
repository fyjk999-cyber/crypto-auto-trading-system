# FACTOR ARCHITECTURE

## Canonical Three-Brain Model

The factor system is shared infrastructure used by exactly three logical brains. It is **not** a fourth brain.

### 1. LIVE TRADING BRAIN

Question: **What should the system trade now?**

Canonical factor-aware path:

`Market -> FactorToolGateway -> FactorSnapshot -> Analysis -> Decision -> Risk -> Execution`

Responsibilities:

- calculate/capture approved live factors;
- expose one canonical active `FactorSetVersion`;
- provide immutable decision-time `FactorSnapshot` evidence;
- allow deterministic strategies and bounded LLM tools to consume the approved factor state;
- never perform semantic learning or self-modification inside the live path.

LIVE is the **factor consumer**.

### 2. DAILY LEARNING BRAIN

Question: **What happened, why did it happen, and what was learned?**

Canonical path:

`Replay -> Review -> Factor Attribution -> Error Mining -> Pattern -> Lesson -> Memory`

This brain owns all temporal review levels:

- DAILY
- WEEKLY
- MONTHLY
- YEARLY

Responsibilities:

- replay historical decision evidence;
- use the historical `FactorSnapshot` attached to the decision instead of recomputing past factors;
- attribute supporting/opposing/dominant factors;
- detect factor conflict, decay, redundancy, health/data issues and regime mismatch;
- separate decision quality from outcome quality;
- create candidate/confirmed lessons through the canonical memory facade;
- never mutate active production factor configuration directly.

DAILY LEARNING is the **factor reviewer**.

### 3. EVOLUTION BRAIN

Question: **How should the next version become better?**

Canonical path:

`Research -> Factor Discovery -> Hypothesis -> Self Modification -> Candidate -> Validation -> Safe Promotion`

Responsibilities:

- consume confirmed lessons and research evidence;
- discover/propose factor, weight, parameter and combination candidates;
- perform candidate-only modification in isolated workspaces;
- validate challengers against immutable gates;
- promote only through the existing Safe Promotion path;
- never bypass RiskEngine, ExecutionAuthority, Ledger, order safety, reconciliation or production promotion rules.

EVOLUTION is the **factor evolver**.

## Shared Factor Infrastructure

The three brains share one factor infrastructure surface:

- `FactorToolGateway`
- `FactorCaptureEngine`
- `FactorEngine`
- `FactorRegistry`
- `FactorCatalog`
- `FactorSetVersion`
- immutable `FactorSnapshot`
- factor persistence/evidence services
- read-only live factor tools

The intended relationship is:

```text
LIVE TRADING BRAIN
  calculate / capture / consume
            |
            v
      FactorSnapshot
            |
            v
DAILY LEARNING BRAIN
  review / attribute / detect decay
            |
            v
         Lessons
            |
            v
EVOLUTION BRAIN
  discover / hypothesize / validate
            |
            v
Validated FactorSetVersion
            |
            +----------------------> LIVE TRADING BRAIN
```

## Canonical Wiring Rule

A trading decision must not create independent factor views for strategy, LLM and replay.

The required ordering is:

1. Market inputs reach the canonical `FactorToolGateway`.
2. The gateway produces one decision-time immutable `FactorSnapshot` under one active `FactorSetVersion`.
3. Analysis/strategy consumes that snapshot.
4. LLM tools, when used, read from the same canonical factor surface and may not mutate factors.
5. `DecisionEvidence` records the snapshot/version reference.
6. DAILY LEARNING replays the historical snapshot.
7. EVOLUTION may propose a new factor version only through candidate + validation + safe promotion.

This prevents the invalid state:

```text
Strategy -> FactorSet A
LLM      -> FactorSet B
Replay   -> recomputed FactorSet C
```

for one logical decision.

## Ownership Rule for Existing Modules

Existing factor/alpha/evolution modules may remain as providers, but every public capability must resolve to one of these roles:

- **LIVE** — calculate/capture/consume;
- **DAILY** — replay/review/attribute/learn;
- **EVOLUTION** — research/discover/candidate/validate;
- **SHARED INFRASTRUCTURE** — registry, persistence, evidence, versioning, observability.

No new `FactorBrain`, `factor_engine_v2`, `factor_learning_v2`, `factor_evolution_v2` or other parallel top-level architecture should be introduced.

## Audit Snapshot Note

A read-only AST/import audit performed on baseline `eacf033830b06c8394cfc77b8a9f77d31a6bd776` found that the foundational factor components existed, but the inspected baseline still had incomplete canonical consumption/wiring and multiple competing entry points. Those findings are preserved in `docs/FACTOR_SYSTEM_REFACTOR_AUDIT.md` as a historical audit snapshot; later commits may have advanced implementation beyond that baseline.
