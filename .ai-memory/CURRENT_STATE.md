# CURRENT_STATE

Phase 17-27 core implemented:
- perpetual domain, margin, funding, liquidation
- true LONG/SHORT paper engine on ledger
- futures ledger projection + journal-balanced tests
- leverage control chain (hard max 6x)
- L1-L4 governance, risk/adversarial reviewers, human approval timeout
- stress engine, trade/failure memory, daily review, backtest V2, walk-forward
- docs and CODEX_UI_HANDOFF generated
Tests: 169 passing. Ruff clean. agent-project-test PASS.
Known blockers for later phases: Binance Futures/Testnet require external API keys;
PostgreSQL/cloud require external infrastructure credentials.
