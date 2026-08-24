# Cloudflare Architecture

Edge Worker -> Cloudflare Container (Python trading core) -> PostgreSQL / Binance Testnet / R2 backups.
Worker is edge-only; Ledger stays PostgreSQL; R2 stores backups only.
