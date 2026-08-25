"""Factor engine: calculate factors from candles and market data."""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.factors.calculators import funding as funding_calc
from crypto_trader.factors.calculators import momentum as momentum_calc
from crypto_trader.factors.calculators import open_interest as oi_calc
from crypto_trader.factors.calculators import orderflow as orderflow_calc
from crypto_trader.factors.calculators import trend as trend_calc
from crypto_trader.factors.calculators import volatility as vol_calc
from crypto_trader.factors.calculators import volume as volume_calc
from crypto_trader.factors.models import FactorResult
from crypto_trader.factors.registry import FactorRegistry


class FactorEngine:
    def __init__(self, registry: FactorRegistry | None = None) -> None:
        self.registry = registry or FactorRegistry()

    def calculate(
        self, symbol: str, timeframe: str, candles: list[dict], market_data: dict | None = None
    ) -> list[FactorResult]:
        md = market_data or {}
        results: list[FactorResult] = []
        calculators = {
            "trend": trend_calc.calculate,
            "momentum": momentum_calc.calculate,
            "volatility": vol_calc.calculate,
            "volume": volume_calc.calculate,
        }
        for name, fn in calculators.items():
            try:
                raw = fn(symbol, timeframe, candles)
                results.append(FactorResult(**raw))
            except Exception:
                results.append(
                    FactorResult(
                        name,
                        symbol,
                        timeframe,
                        Decimal("0"),
                        Decimal("0"),
                        metadata={"error": "calculation_failed"},
                    )
                )
        try:
            raw = orderflow_calc.calculate(
                symbol,
                timeframe,
                candles,
                bid_volume=md.get("bid_volume", Decimal("0")),
                ask_volume=md.get("ask_volume", Decimal("0")),
            )
            results.append(FactorResult(**raw))
        except Exception:
            results.append(
                FactorResult(
                    "orderflow",
                    symbol,
                    timeframe,
                    Decimal("0"),
                    Decimal("0"),
                    metadata={"error": "calculation_failed"},
                )
            )
        try:
            raw = funding_calc.calculate(
                symbol,
                timeframe,
                funding_rate=md.get("funding_rate", Decimal("0")),
                average_funding=md.get("average_funding"),
            )
            results.append(FactorResult(**raw))
        except Exception:
            results.append(
                FactorResult(
                    "funding",
                    symbol,
                    timeframe,
                    Decimal("0"),
                    Decimal("0"),
                    metadata={"error": "calculation_failed"},
                )
            )
        try:
            raw = oi_calc.calculate(
                symbol,
                timeframe,
                oi_current=md.get("open_interest", Decimal("0")),
                oi_previous=md.get("open_interest_previous"),
                price_change=md.get("price_change"),
            )
            results.append(FactorResult(**raw))
        except Exception:
            results.append(
                FactorResult(
                    "open_interest",
                    symbol,
                    timeframe,
                    Decimal("0"),
                    Decimal("0"),
                    metadata={"error": "calculation_failed"},
                )
            )
        return results

    def calculate_all(
        self, symbol: str, timeframe: str, candles: list[dict], market_data: dict | None = None
    ) -> dict[str, FactorResult]:
        return {r.factor_name: r for r in self.calculate(symbol, timeframe, candles, market_data)}
