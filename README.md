# Crypto Automated Trading System

Exchange-independent, event-driven, ledger-first, idempotent, recoverable **Crypto-Native Automated Trading Infrastructure**.

This project is a new, standalone system. It is **not** a fork or copy of SilverQuant or Kalshi. SilverQuant and the Kalshi paper traders were used only as read-only architectural references (see `docs/reference-source-baseline.md` and `docs/SOURCE_PROVENANCE.md`).

## Principles
- **Ledger first**: the double-entry journal is the single money truth; Account/Position/PnL are replayable projections.
- **Event driven**: async order state machine handles ack/fill reordering, duplicate events, timeouts, and races.
- **Decimal safe**: every financial field (`Price`, `Quantity`, `Money`, `Balance`, `Fee`, `PnL`, `CostBasis`, `Margin`, `Funding`) uses `Decimal`. Binary floats are forbidden in core money paths.
- **Exchange independent**: adapters own all exchange-specific JSON, errors, and transport.
- **Single writer**: DB-backed run lease prevents duplicate order submission across engine instances.
- **Paper/Live share one core**: `SimulatedExchangeAdapter` implements the same `ExchangeAdapter` contract as Binance.

## Quickstart
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest            # full suite
alembic upgrade head
uvicorn crypto_trader.api.app:app --reload
```

## Layout
```
src/crypto_trader/
  domain/ market_data/ exchange/ execution/ order/ ledger/
  portfolio/ risk/ runtime/ simulator/ reconciliation/
  persistence/ observability/ strategy/ api/
```

## Modes
`TRADING_MODE=PAPER` is the default. `LIVE_TRADING_ENABLED` defaults to `false`.
No real-money orders are placed by the harness test suite.

## Documentation
- `SPAC. single source of truth (goal, architecture, invariants, DoD).
- `HARNESS_GOAL. long-term goal.
- `docs/phase1_brainstorm. product-boundary decisions.
- `docs/reference-source-baseline. read-only source protection baseline.
- `docs/SOURCE_PROVENANCE. code provenance.
- `FINAL_REPORT. final delivery report.

## Reference sources (READ-ONLY)
- SilverQuant
- kalshi-paper-trader
- kalshi-paper-trader-v2

Architecture was reused; code was copied out only where noted and then modified in this new project. Reference repositories were never modified.
