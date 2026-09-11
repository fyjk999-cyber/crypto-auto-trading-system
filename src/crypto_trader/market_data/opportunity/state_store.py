"""Restart-durable Market-Intelligence scanner state (§6.2/§6.3).

Fairness and OI-sampling progress must not silently reset on every restart,
otherwise the same symbols can be re-favoured forever by process restarts. The
state stored here is purely operational scheduling state — never market facts,
never authority:

    rotation cursor + order
    per-symbol fairness clocks (observed / analysed / LLM-researched)
    timestamped OI samples (bounded)
    scan counters (cycles, overruns)

It is written to the non-secret ``runtime_settings`` key/value table, so no
schema migration is needed and no secret can leak. A corrupt/absent value is
ignored (the scanner simply starts fresh) rather than failing the runtime.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from crypto_trader.persistence.models import RuntimeSettingORM

SCANNER_STATE_KEY = "market_intelligence.scanner_state"
SCANNER_STATE_VERSION = 1
MAX_STATE_BYTES = 400_000


class ScannerStateStore:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        self.last_error: str | None = None

    async def load(self) -> dict | None:
        try:
            async with self.session_factory() as session:
                row = await session.get(RuntimeSettingORM, SCANNER_STATE_KEY)
        except Exception as exc:  # a settings read must never break startup
            self.last_error = f"{type(exc).__name__}"[:80]
            return None
        if row is None or not row.value:
            return None
        try:
            payload = json.loads(row.value)
        except (TypeError, ValueError):
            self.last_error = "MALFORMED_STATE"
            return None
        if not isinstance(payload, dict) or payload.get("version") != SCANNER_STATE_VERSION:
            return None
        return payload

    async def save(self, payload: dict) -> bool:
        try:
            encoded = json.dumps(payload, default=str)
        except (TypeError, ValueError):
            self.last_error = "UNSERIALISABLE_STATE"
            return False
        if len(encoded) > MAX_STATE_BYTES:
            self.last_error = "STATE_TOO_LARGE"
            return False
        try:
            async with self.session_factory() as session:
                row = await session.get(RuntimeSettingORM, SCANNER_STATE_KEY)
                if row is None:
                    session.add(
                        RuntimeSettingORM(
                            key=SCANNER_STATE_KEY,
                            value=encoded,
                            updated_at=datetime.now(UTC),
                            updated_by="opportunity_scanner",
                        )
                    )
                else:
                    row.value = encoded
                    row.updated_at = datetime.now(UTC)
                    row.updated_by = "opportunity_scanner"
                await session.commit()
        except Exception as exc:  # persistence is best-effort, never fatal
            self.last_error = f"{type(exc).__name__}"[:80]
            return False
        return True
