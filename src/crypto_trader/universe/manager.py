"""Universe manager: discover tradable assets with OKX mapping and classification."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_trader.exchange.symbol_mapper import SymbolMapper


@dataclass
class UniverseAsset:
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    contract_type: str
    tick_size: Decimal
    lot_size: Decimal
    max_leverage: Decimal
    status: str
    enabled: bool
    liquidity_score: float
    category: str


DEFAULT_UNIVERSE = [
    ("BTCUSDT", "BTC-USDT-SWAP", "BTC", "USDT", "SWAP", "0.1", "0.001", "100", "LARGE_CAP"),
    ("ETHUSDT", "ETH-USDT-SWAP", "ETH", "USDT", "SWAP", "0.01", "0.01", "75", "LARGE_CAP"),
    ("SOLUSDT", "SOL-USDT-SWAP", "SOL", "USDT", "SWAP", "0.001", "0.1", "50", "LARGE_CAP"),
    ("PEPEUSDT", "PEPE-USDT-SWAP", "PEPE", "USDT", "SWAP", "0.0000001", "1000", "20", "MEME"),
]


class UniverseManager:
    def __init__(self, assets: list[tuple] | None = None) -> None:
        self.assets: list[UniverseAsset] = []
        for item in assets or DEFAULT_UNIVERSE:
            self.assets.append(self._build(item))

    def _build(self, item: tuple) -> UniverseAsset:
        symbol, provider_symbol, base, quote, contract_type, tick, lot, lev, category = item
        return UniverseAsset(
            symbol=symbol,
            provider_symbol=provider_symbol,
            base_asset=base,
            quote_asset=quote,
            contract_type=contract_type,
            tick_size=Decimal(tick),
            lot_size=Decimal(lot),
            max_leverage=Decimal(lev),
            status="TRADING",
            enabled=True,
            liquidity_score=float(lev),
            category=category,
        )

    def list_enabled(self) -> list[UniverseAsset]:
        return [a for a in self.assets if a.enabled]

    def get(self, symbol: str) -> UniverseAsset | None:
        for asset in self.assets:
            if asset.symbol == symbol:
                return asset
        return None

    def provider_symbol(self, symbol: str) -> str:
        mapper = SymbolMapper()
        try:
            return mapper.to_okx(symbol)
        except ValueError:
            return symbol

    def to_dict(self) -> list[dict]:
        return [
            {
                "symbol": a.symbol,
                "provider_symbol": a.provider_symbol,
                "base_asset": a.base_asset,
                "quote_asset": a.quote_asset,
                "contract_type": a.contract_type,
                "tick_size": str(a.tick_size),
                "lot_size": str(a.lot_size),
                "max_leverage": str(a.max_leverage),
                "status": a.status,
                "enabled": a.enabled,
                "liquidity_score": a.liquidity_score,
                "category": a.category,
            }
            for a in self.assets
        ]
