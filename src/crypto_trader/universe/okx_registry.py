"""Dynamic, provenance-preserving OKX market universe registry.

Discovery is intentionally broader than execution.  An instrument can be in
ALL_MARKET while unavailable for observation, analysis, or PAPER execution.
No layer is inferred from a hard-coded trading-symbol list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.money import D
from crypto_trader.exchange.okx import OKXAdapter

SUPPORTED_INSTRUMENT_TYPES = ("SPOT", "SWAP", "FUTURES")


@dataclass(frozen=True)
class OKXInstrumentMetadata:
    instrument_id: str
    exchange: str
    instrument_type: str
    base: str
    quote: str
    settle_currency: str | None
    contract_value: Decimal | None
    contract_multiplier: Decimal | None
    tick_size: Decimal
    lot_size: Decimal
    min_size: Decimal
    state: str
    listing_status: str
    source_timestamp: datetime
    received_timestamp: datetime

    @classmethod
    def from_okx(cls, raw: dict, received_at: datetime) -> OKXInstrumentMetadata:
        instrument_id = str(raw.get("instId", ""))
        instrument_type = str(raw.get("instType", ""))
        if not instrument_id or instrument_type not in SUPPORTED_INSTRUMENT_TYPES:
            raise ValueError("invalid or unsupported OKX instrument metadata")
        listing_time = raw.get("listTime")
        source_timestamp = (
            datetime.fromtimestamp(int(listing_time) / 1000, tz=UTC)
            if listing_time not in (None, "", "0")
            else received_at
        )
        return cls(
            instrument_id=instrument_id,
            exchange="OKX",
            instrument_type=instrument_type,
            base=str(raw.get("baseCcy", "")),
            quote=str(raw.get("quoteCcy", "")),
            settle_currency=str(raw["settleCcy"]) if raw.get("settleCcy") else None,
            contract_value=D(raw["ctVal"]) if raw.get("ctVal") else None,
            contract_multiplier=D(raw["ctMult"]) if raw.get("ctMult") else None,
            tick_size=D(raw.get("tickSz", "0")),
            lot_size=D(raw.get("lotSz", "0")),
            min_size=D(raw.get("minSz", "0")),
            state=str(raw.get("state", "unknown")),
            listing_status=str(raw.get("state", "unknown")),
            source_timestamp=source_timestamp,
            received_timestamp=received_at,
        )


class OKXMarketUniverse:
    """Explicit ALL_MARKET -> OBSERVABLE -> ANALYSIS -> EXECUTABLE layers."""

    def __init__(self, client: OKXAdapter) -> None:
        self.client = client
        self.all_market: dict[str, OKXInstrumentMetadata] = {}
        self.observable: set[str] = set()
        self.analysis: set[str] = set()
        self.executable: set[str] = set()

    async def discover(self) -> list[OKXInstrumentMetadata]:
        received_at = datetime.now(UTC)
        discovered: dict[str, OKXInstrumentMetadata] = {}
        for instrument_type in SUPPORTED_INSTRUMENT_TYPES:
            for raw in await self.client.get_instruments(instrument_type):
                metadata = OKXInstrumentMetadata.from_okx(raw, received_at)
                discovered[metadata.instrument_id] = metadata
        self.all_market = discovered
        valid_ids = set(discovered)
        self.observable.intersection_update(valid_ids)
        self.analysis.intersection_update(valid_ids)
        self.executable.intersection_update(valid_ids)
        return list(discovered.values())

    def set_observable(self, instrument_id: str, *, factual_data_fresh: bool) -> None:
        self._require_known(instrument_id)
        if factual_data_fresh:
            self.observable.add(instrument_id)
        else:
            self.observable.discard(instrument_id)
            self.analysis.discard(instrument_id)
            self.executable.discard(instrument_id)

    def set_analysis(self, instrument_id: str, *, allowed: bool) -> None:
        self._require_known(instrument_id)
        if allowed and instrument_id in self.observable:
            self.analysis.add(instrument_id)
        else:
            self.analysis.discard(instrument_id)
            self.executable.discard(instrument_id)

    def set_executable(self, instrument_id: str, *, compatible: bool) -> None:
        self._require_known(instrument_id)
        if compatible and instrument_id in self.analysis:
            self.executable.add(instrument_id)
        else:
            self.executable.discard(instrument_id)

    def layer(self, name: str) -> list[OKXInstrumentMetadata]:
        if name == "ALL_MARKET":
            ids = set(self.all_market)
        elif name == "OBSERVABLE":
            ids = self.observable
        elif name == "ANALYSIS":
            ids = self.analysis
        elif name == "EXECUTABLE":
            ids = self.executable
        else:
            raise ValueError(f"unknown universe layer: {name}")
        return [self.all_market[instrument_id] for instrument_id in sorted(ids)]

    def _require_known(self, instrument_id: str) -> None:
        if instrument_id not in self.all_market:
            raise KeyError(f"instrument is not in ALL_MARKET: {instrument_id}")
