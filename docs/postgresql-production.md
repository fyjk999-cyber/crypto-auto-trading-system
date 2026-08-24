# PostgreSQL Production

SQLite stays for unit/local. Production uses PostgreSQL with asyncpg.
Alembic migrations cover ledger/orders/fills/futures/margin/funding/memory/reviews.
Fresh upgrade, V1 upgrade, and PHASE16 upgrade must be tested.
