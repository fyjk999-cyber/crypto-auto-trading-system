"""OPS-only registry refresh entrypoint.

Usage (never from the trading runtime):
    python -m crypto_trader.market_registry.refresh [DB_PATH]

Writes the current OKX instrument universe into `okx_instruments` (truth
source for the dynamic market universe) and prints a JSON snapshot summary.
"""
from __future__ import annotations

import json
import sys

from crypto_trader.market_registry.registry import refresh_sync


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    db_path = argv[0] if argv else "data/crypto_trader.db"
    snapshot = refresh_sync(db_path)
    print(json.dumps(snapshot, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
