"""Derivatives intelligence: funding, open interest, liquidation parsing."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.domain.money import D


@dataclass
class DerivativesSnapshot:
    symbol: str
    funding_rate: Decimal | None = None
    next_funding_time: str | None = None
    open_interest: Decimal | None = None
    oi_change_pct: Decimal | None = None
    long_liquidation: Decimal = Decimal("0")
    short_liquidation: Decimal = Decimal("0")
    long_short_ratio: Decimal | None = None


class DerivativesEngine:
    @staticmethod
    def parse_funding(raw: dict) -> Decimal | None:
        if not raw:
            return None
        try:
            value = D(raw.get("fundingRate", raw.get("funding_rate")))
        except Exception:
            return None
        return value if value != 0 else None

    @staticmethod
    def parse_open_interest(raw: dict) -> tuple[Decimal | None, Decimal | None]:
        if not raw:
            return None, None
        try:
            current = D(raw["openInterest"])
        except Exception:
            return None, None
        previous = raw.get("previousOpenInterest")
        if previous is None:
            return current, None
        try:
            change = (current - D(previous)) / D(previous) * D("100")
        except Exception:
            change = None
        return current, change

    @staticmethod
    def parse_liquidations(raw: dict) -> tuple[Decimal, Decimal]:
        try:
            long_liq = D(raw.get("longLiquidation", "0"))
            short_liq = D(raw.get("shortLiquidation", "0"))
        except Exception:
            return Decimal("0"), Decimal("0")
        return long_liq, short_liq
