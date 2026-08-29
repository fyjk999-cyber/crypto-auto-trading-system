"""Canonical symbol mapper: strategies only see canonical symbols."""

from dataclasses import dataclass

DEFAULT_TRADING_SYMBOLS: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "SUIUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "DOTUSDT",
    "NEARUSDT",
    "APTUSDT",
    "ARBUSDT",
    "OPUSDT",
    "TONUSDT",
    "TRXUSDT",
    "UNIUSDT",
    "HYPEUSDT",
    "ZECUSDT",
    "ENAUSDT",
    "WLDUSDT",
    "ONDOUSDT",
    "FILUSDT",
    "TAOUSDT",
    "AAVEUSDT",
    "XLMUSDT",
    "HBARUSDT",
)


@dataclass(frozen=True)
class SymbolMapping:
    canonical: str
    binance: str
    okx: str


class SymbolMapper:
    MAPPINGS = {
        symbol: SymbolMapping(
            canonical=symbol,
            binance=symbol,
            okx=f"{symbol.removesuffix('USDT')}-USDT-SWAP",
        )
        for symbol in DEFAULT_TRADING_SYMBOLS
    }

    def to_binance(self, canonical: str) -> str:
        mapping = self.MAPPINGS.get(canonical.upper())
        if mapping is None:
            raise ValueError(f"unknown canonical symbol: {canonical}")
        return mapping.binance

    def to_okx(self, canonical: str) -> str:
        mapping = self.MAPPINGS.get(canonical.upper())
        if mapping is None:
            raise ValueError(f"unknown canonical symbol: {canonical}")
        return mapping.okx

    def to_canonical(self, raw: str) -> str:
        normalized = raw.upper()
        if normalized in self.MAPPINGS:
            return normalized
        for mapping in self.MAPPINGS.values():
            if normalized in (mapping.binance, mapping.okx):
                return mapping.canonical
        raise ValueError(f"unknown exchange symbol: {raw}")

    def supported_symbols(self) -> tuple[str, ...]:
        return tuple(self.MAPPINGS)
