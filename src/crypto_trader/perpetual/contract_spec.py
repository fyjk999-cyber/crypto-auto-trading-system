"""Explicit provenance for perp contract_size / contract_multiplier."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from crypto_trader.domain.money import D


class ContractSpecStatus(StrEnum):
    PROVEN = "PROVEN"
    UNPROVEN = "UNPROVEN"


@dataclass(frozen=True)
class ContractSpecProvenance:
    instrument_id: str
    contract_size: Decimal | None
    contract_multiplier: Decimal | None
    status: ContractSpecStatus
    source: str
    observed_at: datetime
    reason: str | None = None
    watermark: str | None = None

    @property
    def proven(self) -> bool:
        return self.status == ContractSpecStatus.PROVEN


def unproven_spec(instrument_id: str, *, reason: str) -> ContractSpecProvenance:
    return ContractSpecProvenance(
        instrument_id=instrument_id,
        contract_size=None,
        contract_multiplier=None,
        status=ContractSpecStatus.UNPROVEN,
        source="NONE",
        observed_at=datetime.now(UTC),
        reason=reason,
    )


def spec_from_instrument(
    instrument_id: str,
    instrument,
) -> ContractSpecProvenance:
    if instrument is None:
        return unproven_spec(instrument_id, reason="INSTRUMENT_METADATA_UNAVAILABLE")
    if isinstance(instrument, Mapping):
        symbol = instrument.get("symbol")
        instrument_type = str(instrument.get("instrument_type") or "")
        try:
            contract_size = D(instrument.get("contract_size"))
            multiplier = D(instrument.get("contract_multiplier"))
        except Exception:
            return unproven_spec(instrument_id, reason="INSTRUMENT_SPEC_UNPARSEABLE")
    else:
        symbol = getattr(instrument, "symbol", None)
        instrument_type = str(getattr(instrument, "instrument_type", "") or "")
        try:
            contract_size = D(instrument.contract_size)
            multiplier = D(instrument.contract_multiplier)
        except Exception:
            return unproven_spec(instrument_id, reason="INSTRUMENT_SPEC_UNPARSEABLE")
    if symbol is not None and str(symbol) != instrument_id:
        return unproven_spec(
            instrument_id, reason=f"INSTRUMENT_METADATA_SYMBOL_MISMATCH:{symbol}"
        )
    if instrument_type != "LINEAR_PERP":
        return unproven_spec(
            instrument_id,
            reason=f"INSTRUMENT_TYPE_NOT_LINEAR_PERP:{instrument_type or 'MISSING'}",
        )
    if contract_size <= 0 or multiplier <= 0:
        return unproven_spec(instrument_id, reason="INSTRUMENT_SPEC_UNPARSEABLE")
    if contract_size <= 0 or multiplier <= 0:
        return unproven_spec(instrument_id, reason="INSTRUMENT_SPEC_NOT_POSITIVE")
    return ContractSpecProvenance(
        instrument_id=instrument_id,
        contract_size=contract_size,
        contract_multiplier=multiplier,
        status=ContractSpecStatus.PROVEN,
        source="OKX_INSTRUMENT_METADATA",
        observed_at=datetime.now(UTC),
    )


def spec_from_order_metadata(
    instrument_id: str,
    order,
) -> ContractSpecProvenance:
    if order is None:
        return unproven_spec(instrument_id, reason="ORDER_METADATA_UNAVAILABLE")
    if str(order.symbol) != instrument_id:
        return unproven_spec(
            instrument_id,
            reason=f"ORDER_SYMBOL_MISMATCH:{order.symbol}",
        )
    if hasattr(order, "metadata_json"):
        metadata = getattr(order, "metadata_json", None) or {}
    else:
        metadata = getattr(order, "metadata", None) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    if str(metadata.get("instrument_type") or "") != "LINEAR_PERP":
        return unproven_spec(
            instrument_id,
            reason="ORDER_INSTRUMENT_TYPE_NOT_LINEAR_PERP",
        )
    try:
        contract_size = D(metadata["contract_size"])
        multiplier = D(metadata["contract_multiplier"])
    except Exception:
        return unproven_spec(instrument_id, reason="ORDER_SPEC_MISSING")
    if contract_size <= 0 or multiplier <= 0:
        return unproven_spec(instrument_id, reason="ORDER_SPEC_NOT_POSITIVE")
    return ContractSpecProvenance(
        instrument_id=instrument_id,
        contract_size=contract_size,
        contract_multiplier=multiplier,
        status=ContractSpecStatus.PROVEN,
        source="DURABLE_ORDER_METADATA",
        observed_at=datetime.now(UTC),
        watermark=f"order:{getattr(order, 'internal_order_id', 'unknown')}",
    )
