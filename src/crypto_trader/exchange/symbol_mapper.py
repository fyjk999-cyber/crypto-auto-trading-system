"""Canonical symbol mapper: strategies only see canonical symbols."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolMapping:
    canonical: str
    binance: str
    okx: str


class SymbolMapper:
    MAPPINGS = {
        "BTCUSDT": SymbolMapping(canonical="BTCUSDT", binance="BTCUSDT", okx="BTC-USDT-SWAP"),
        "ETHUSDT": SymbolMapping(canonical="ETHUSDT", binance="ETHUSDT", okx="ETH-USDT-SWAP"),
        "SOLUSDT": SymbolMapping(canonical="SOLUSDT", binance="SOLUSDT", okx="SOL-USDT-SWAP"),
    }

    def to_binance(self, canonical: str) -> str:
        mapping = self.MAPPINGS.get(canonical)
        if mapping is None:
            raise ValueError(f"unknown canonical symbol: {canonical}")
        return mapping.binance

    def to_okx(self, canonical: str) -> str:
        mapping = self.MAPPINGS.get(canonical)
        if mapping is not None:
            return mapping.okx
        normalized = canonical.upper()
        if normalized.endswith("USDT") and normalized[:-4].isalnum():
            return f"{normalized[:-4]}-USDT-SWAP"
        raise ValueError(f"unknown canonical symbol: {canonical}")

    def to_canonical(self, raw: str) -> str:
        if raw in self.MAPPINGS:
            return raw
        for mapping in self.MAPPINGS.values():
            if raw in (mapping.binance, mapping.okx):
                return mapping.canonical
        normalized = raw.upper()
        if normalized.endswith("-USDT-SWAP"):
            base = normalized.removesuffix("-USDT-SWAP")
            if base and base.replace("-", "").isalnum():
                return f"{base.replace('-', '')}USDT"
        raise ValueError(f"unknown exchange symbol: {raw}")
