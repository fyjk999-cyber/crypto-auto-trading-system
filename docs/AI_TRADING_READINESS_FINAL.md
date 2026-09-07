# AI Trading Readiness

- Updated: 2026-09-07
- Canonical decision authority: `ChiefTraderEngine` / DeepSeek only
- Quant, factor, and strategy components: read-only evidence tools
- Canonical bootstrap: verified by deterministic integration tests
- Runtime mode: PAPER with local simulated execution
- Market data: factual OKX public market data
- Live trading: disabled
- Forced trades, synthetic decisions, fake fills, and fake episodes: disabled
- Real DeepSeek runtime decisions observed: `WAIT` and `NO_TRADE`
- Natural directional entry lineage: pending a naturally qualifying decision
- Natural full exit lineage: pending a factual natural entry and later exit
- Final project status: incomplete until both natural lineages are observed and audited

`AI_AUTONOMOUS_RUNTIME_READY` here means the canonical bootstrap starts the
single ChiefTrader decision loop and preserves Risk and ExecutionAuthority. It
does not mean real-money readiness and does not claim that a natural end-to-end
entry and exit has already occurred.
