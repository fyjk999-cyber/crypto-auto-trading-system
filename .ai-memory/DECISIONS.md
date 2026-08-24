# DECISIONS

- 2026-08-24: Ledger is the single money truth; Account/Position/PnL are projections.
- 2026-08-24: Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2 async + Alembic + SQLite(aiosqlite) tests.
- 2026-08-24: All financial arithmetic uses Decimal. Binary float forbidden in core financial fields.
- 2026-08-24: Binance first adapter; OKX/Bybit boundaries only.
- 2026-08-24: SimulatedExchangeAdapter shares the same adapter contract; no separate paper core.
- 2026-08-24: DB-backed run lease with atomic CAS renew; single writer.
