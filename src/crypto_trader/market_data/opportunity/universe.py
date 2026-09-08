"""Dynamic factual OKX instrument universe (MASTER DIRECTIVE §8).

Sources the tradable universe from the real OKX public instruments endpoint
(no hardcoded canonical list, no static fallback). Normalizes OKX SWAP
inst-ids to the internal canonical symbol format via SymbolMapper. Caches
with a bounded refresh period and fails closed: if no ever-valid snapshot
exists and the provider errors, UniverseUnavailable is raised — the system
never invents instruments.

This layer owns NO trade direction. It answers only:
"which markets factually exist and are currently live on OKX?".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.exchange.symbol_mapper import SymbolMapper

INSTRUMENT_TYPE = "SWAP"
DEFAULT_REFRESH_SECONDS = 6 * 3600.0
MAX_STALE_SECONDS = 24 * 3600.0


class UniverseUnavailable(RuntimeError):
    """Raised when no factual universe snapshot is available (fail closed)."""


@dataclass(frozen=True, slots=True)
class Instrument:
    """Factual instrument identity (normalized internal symbol + raw row)."""

    symbol: str  # internal canonical, e.g. BTCUSDT
    inst_id: str  # OKX inst-id, e.g. BTC-USDT-SWAP
    state: str
    settle_ccy: str
    ct_val: str
    list_time: str
    raw: dict


@dataclass(slots=True)
class UniverseSnapshot:
    instruments: dict[str, Instrument]
    fetched_at: datetime
    source: str = "OKX /api/v5/public/instruments"

    @property
    def size(self) -> int:
        return len(self.instruments)


@dataclass
class UniverseStats:
    last_refresh_at: datetime | None = None
    last_refresh_ok: bool = False
    last_error: str | None = None
    refresh_count: int = 0
    total_instruments: int = 0
    usdt_swap_count: int = 0
    excluded_malformed: int = 0
    excluded_not_live: int = 0
    refresh_history: list[dict] = field(default_factory=list)


def _normalize_symbol(inst_row: dict) -> str | None:
    """OKX inst-id -> internal canonical symbol, or None when malformed."""
    inst_id = str(inst_row.get("instId") or "")
    if not inst_id.endswith("-USDT-SWAP"):
        return None
    base = inst_id.removesuffix("-USDT-SWAP")
    if not base or not base.replace("-", "").isalnum():
        return None
    return f"{base}USDT"


class OkxUniverseManager:
    """Bounded-cache factual universe sourced from OKX instruments metadata."""

    def __init__(
        self,
        okx_client,
        *,
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
        max_stale_seconds: float = MAX_STALE_SECONDS,
        clock=None,
    ) -> None:
        self._client = okx_client
        self._refresh_seconds = float(refresh_seconds)
        self._max_stale_seconds = float(max_stale_seconds)
        self._clock = clock or (lambda: time.monotonic())
        self._snapshot: UniverseSnapshot | None = None
        self._last_refresh_mono: float | None = None
        self.stats = UniverseStats()

    # ------------------------------------------------------------------ read
    def get_snapshot(self) -> UniverseSnapshot:
        """Return the current factual snapshot (fail closed when none)."""
        if self._snapshot is None:
            raise UniverseUnavailable("OKX universe has never been fetched")
        return self._snapshot

    def symbols(self) -> list[str]:
        snap = self.get_snapshot()
        return sorted(snap.instruments)

    def is_stale(self) -> bool:
        if self._snapshot is None or self._last_refresh_mono is None:
            return True
        return (self._clock() - self._last_refresh_mono) >= self._refresh_seconds

    def age_seconds(self) -> float | None:
        if self._last_refresh_mono is None:
            return None
        return self._clock() - self._last_refresh_mono

    def too_stale_to_serve(self) -> bool:
        age = self.age_seconds()
        return age is None or age > self._max_stale_seconds

    # ---------------------------------------------------------------- update
    async def refresh(self, *, force: bool = False) -> UniverseSnapshot:
        """Fetch instruments from OKX. Fail-closed semantics:

        - success: replace snapshot atomically, record stats;
        - failure with a still-fresh cached snapshot: serve cache, record error;
        - failure with no/too-stale snapshot: raise UniverseUnavailable.
        """
        if not force and self._snapshot is not None and not self.is_stale():
            return self._snapshot
        now = datetime.now(UTC)
        self.stats.refresh_count += 1
        try:
            rows = await self._client.get_instruments(INSTRUMENT_TYPE)
        except Exception as exc:  # provider error -> fail closed
            self.stats.last_refresh_ok = False
            self.stats.last_error = f"{type(exc).__name__}: {exc}"[:200]
            self.stats.refresh_history.append(
                {"at": now.isoformat(), "ok": False, "error": self.stats.last_error}
            )
            self._trim_history()
            if self._snapshot is not None and not self.too_stale_to_serve():
                return self._snapshot
            raise UniverseUnavailable(
                f"OKX instruments unavailable and no fresh cache: {self.stats.last_error}"
            ) from exc

        instruments: dict[str, Instrument] = {}
        malformed = 0
        not_live = 0
        mapper = SymbolMapper()
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("instId") or ""):
                malformed += 1
                continue
            if str(row.get("instType") or INSTRUMENT_TYPE) != INSTRUMENT_TYPE:
                continue
            symbol = _normalize_symbol(row)
            if symbol is None:
                malformed += 1
                continue
            # cross-check against the mapper's factual conversion rule; a
            # normalized symbol whose OKX round-trip disagrees is malformed.
            if mapper.to_okx(symbol) != str(row["instId"]):
                malformed += 1
                continue
            state = str(row.get("state") or "")
            if state != "live":
                not_live += 1
                continue
            inst = Instrument(
                symbol=symbol,
                inst_id=str(row["instId"]),
                state=state,
                settle_ccy=str(row.get("settleCcy") or ""),
                ct_val=str(row.get("ctVal") or ""),
                list_time=str(row.get("listTime") or ""),
                raw={
                    k: row.get(k)
                    for k in (
                        "instId",
                        "instType",
                        "state",
                        "settleCcy",
                        "ctVal",
                        "listTime",
                        "uly",
                    )
                },
            )
            instruments[symbol] = inst
        self._snapshot = UniverseSnapshot(instruments=instruments, fetched_at=now)
        self._last_refresh_mono = self._clock()
        self.stats.last_refresh_at = now
        self.stats.last_refresh_ok = True
        self.stats.last_error = None
        self.stats.total_instruments = len(rows)
        self.stats.usdt_swap_count = len(instruments)
        self.stats.excluded_malformed = malformed
        self.stats.excluded_not_live = not_live
        self.stats.refresh_history.append(
            {
                "at": now.isoformat(),
                "ok": True,
                "total": len(rows),
                "live_usdt_swap": len(instruments),
            }
        )
        self._trim_history()
        return self._snapshot

    def _trim_history(self) -> None:
        if len(self.stats.refresh_history) > 20:
            del self.stats.refresh_history[:-20]
