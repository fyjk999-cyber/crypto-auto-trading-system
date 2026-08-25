"""Factor capture engine: compute all v2.5 factors from candles + market data."""

from __future__ import annotations

import statistics
from decimal import Decimal

from crypto_trader.domain.money import D
from crypto_trader.factors.models import FactorResult


def _close(candle: dict) -> Decimal:
    return D(str(candle.get("close", candle.get("c", "0"))))


def _high(candle: dict) -> Decimal:
    return D(str(candle.get("high", candle.get("h", candle.get("close", candle.get("c", "0"))))))


def _low(candle: dict) -> Decimal:
    return D(str(candle.get("low", candle.get("l", candle.get("close", candle.get("c", "0"))))))


def _volume(candle: dict) -> Decimal:
    return D(str(candle.get("volume", "0")))


class FactorCaptureEngine:
    def capture(
        self, symbol: str, timeframe: str, candles: list[dict], market_data: dict | None = None
    ) -> list[FactorResult]:
        md = market_data or {}
        results: list[FactorResult] = []
        self._capture_price(symbol, timeframe, candles, results)
        self._capture_volume(symbol, timeframe, candles, results)
        self._capture_volatility(symbol, timeframe, candles, results)
        self._capture_orderflow(symbol, timeframe, candles, md, results)
        self._capture_derivatives(symbol, timeframe, md, results)
        return results

    def _add(self, results, factor_id, symbol, timeframe, value, confidence, metadata=None):
        results.append(
            FactorResult(factor_id, symbol, timeframe, value, confidence, metadata=metadata or {})
        )

    def _capture_price(self, symbol, timeframe, candles, results):
        if len(candles) < 2:
            return
        closes = [_close(c) for c in candles]
        prev = closes[-2]
        last = closes[-1]
        ret = (last - prev) / prev if prev > 0 else D("0")
        self._add(
            results,
            "return",
            symbol,
            timeframe,
            max(D("-1"), min(D("1"), ret * D("100"))),
            D("0.9"),
            {"return": str(ret)},
        )
        acc = D("0")
        if len(closes) >= 3 and closes[-3] > 0:
            prev_ret = (closes[-2] - closes[-3]) / closes[-3]
            acc = ret - prev_ret
        momentum = max(D("-1"), min(D("1"), ret * D("100") + acc * D("50")))
        self._add(
            results, "momentum", symbol, timeframe, momentum, D("0.8"), {"acceleration": str(acc)}
        )
        ema = closes[0]
        k = D("2") / D("11")
        for price in closes[1:]:
            ema = price * k + ema * (D("1") - k)
        ema_slope = (ema - (closes[0] if len(closes) < 11 else ema)) * D("100")
        ma = (
            sum(closes[-20:], D("0")) / D(str(len(closes[-20:])))
            if len(closes) >= 20
            else (sum(closes, D("0")) / D(str(len(closes))))
        )
        ma_distance = (last - ma) / ma if ma > 0 else D("0")
        trend = max(D("-1"), min(D("1"), ema_slope + ma_distance * D("10")))
        self._add(
            results,
            "trend",
            symbol,
            timeframe,
            trend,
            D("0.8"),
            {"ema_slope": str(ema_slope), "ma_distance": str(ma_distance)},
        )
        prior_high = (
            max(_high(c) for c in candles[-20:-1]) if len(candles) >= 21 else _high(candles[-1])
        )
        breakout = (
            max(D("0"), min(D("1"), (last - prior_high) / prior_high * D("100")))
            if prior_high > 0
            else D("0")
        )
        self._add(
            results,
            "breakout",
            symbol,
            timeframe,
            breakout,
            D("0.6"),
            {"prior_high": str(prior_high)},
        )
        mean = (
            sum(closes[-20:], D("0")) / D(str(len(closes[-20:])))
            if len(closes) >= 20
            else (sum(closes, D("0")) / D(str(len(closes))))
        )
        std = statistics.pstdev([float(c) for c in closes[-20:]]) if len(closes) >= 20 else 0
        zscore = (float(last) - float(mean)) / std if std > 0 else 0.0
        mr = max(D("-1"), min(D("1"), D(str(-zscore))))
        self._add(
            results, "mean_reversion", symbol, timeframe, mr, D("0.5"), {"zscore": str(zscore)}
        )

    def _capture_volume(self, symbol, timeframe, candles, results):
        if len(candles) < 2:
            return
        vols = [_volume(c) for c in candles]
        recent = vols[-1]
        avg = sum(vols[:-1], D("0")) / D(str(len(vols) - 1)) if len(vols) > 1 else D("0")
        if avg <= 0:
            return
        change = (recent - avg) / avg
        self._add(
            results,
            "volume_change",
            symbol,
            timeframe,
            max(D("-1"), min(D("1"), change * D("0.5"))),
            D("0.8"),
            {"volume_change": str(change)},
        )
        anomaly = min(D("1"), abs(change) / D("3"))
        self._add(
            results,
            "volume_anomaly",
            symbol,
            timeframe,
            anomaly,
            D("0.5") + anomaly * D("0.4"),
            {"volume_anomaly": str(anomaly)},
        )
        price_direction = D("1") if _close(candles[-1]) > _close(candles[-2]) else D("-1")
        vol_direction = D("1") if change > 0 else D("-1")
        divergence = D("0") if price_direction == vol_direction else D("0.7")
        self._add(
            results,
            "volume_divergence",
            symbol,
            timeframe,
            divergence,
            D("0.5"),
            {"price_direction": str(price_direction), "volume_direction": str(vol_direction)},
        )

    def _capture_volatility(self, symbol, timeframe, candles, results):
        if len(candles) < 2:
            return
        highs = [_high(c) for c in candles]
        lows = [_low(c) for c in candles]
        closes = [_close(c) for c in candles]
        trs = []
        for i in range(1, len(candles)):
            tr = max(
                highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])
            )
            trs.append(tr)
        atr = sum(trs, D("0")) / D(str(len(trs))) if trs else D("0")
        self._add(
            results,
            "atr",
            symbol,
            timeframe,
            min(D("1"), atr * D("0.2")),
            D("0.85"),
            {"atr": str(atr)},
        )
        rets = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                rets.append(float((closes[i] - closes[i - 1]) / closes[i - 1]))
        rv = D(str(statistics.pstdev(rets) if len(rets) > 1 else 0.0))
        self._add(
            results,
            "realized_volatility",
            symbol,
            timeframe,
            min(D("1"), rv * D("10")),
            D("0.85"),
            {"realized_volatility": str(rv)},
        )
        hist = sorted([float(r) for r in rets]) if rets else []
        percentile = sum(1 for r in hist if r <= float(rv)) / len(hist) if hist else 0.0
        self._add(
            results,
            "volatility_regime",
            symbol,
            timeframe,
            D(str(percentile)),
            D("0.6"),
            {"volatility_percentile": str(percentile)},
        )

    def _capture_orderflow(self, symbol, timeframe, candles, md, results):
        bid = D(str(md.get("bid_volume", "0")))
        ask = D(str(md.get("ask_volume", "0")))
        total = bid + ask
        if total > 0:
            imbalance = (bid - ask) / total
            self._add(
                results,
                "orderbook_imbalance",
                symbol,
                timeframe,
                max(D("-1"), min(D("1"), imbalance)),
                D("0.75"),
                {"bid_volume": str(bid), "ask_volume": str(ask)},
            )
            self._add(
                results,
                "buy_sell_imbalance",
                symbol,
                timeframe,
                max(D("-1"), min(D("1"), imbalance)),
                D("0.6"),
            )
        else:
            self._add(
                results,
                "orderbook_imbalance",
                symbol,
                timeframe,
                D("0"),
                D("0"),
                {"status": "NO_BOOK"},
            )
            self._add(
                results,
                "buy_sell_imbalance",
                symbol,
                timeframe,
                D("0"),
                D("0"),
                {"status": "NO_TRADES"},
            )
        cvd = D(str(md.get("cvd", "0")))
        self._add(
            results,
            "cvd",
            symbol,
            timeframe,
            max(D("-1"), min(D("1"), cvd / D("1000"))) if cvd != 0 else D("0"),
            D("0.4"),
            {"cvd": str(cvd)},
        )
        aggressive_total = D(str(md.get("aggressive_total", "0")))
        total_volume = D(str(md.get("total_volume", "0")))
        ratio = aggressive_total / total_volume if total_volume > 0 else D("0")
        self._add(
            results,
            "aggressive_trading_ratio",
            symbol,
            timeframe,
            max(D("0"), min(D("1"), ratio)),
            D("0.4"),
            {"aggressive_total": str(aggressive_total)},
        )

    def _capture_derivatives(self, symbol, timeframe, md, results):
        funding = D(str(md.get("funding_rate", "0")))
        self._add(
            results,
            "funding_rate",
            symbol,
            timeframe,
            max(D("-1"), min(D("1"), funding * D("10000"))),
            D("0.7"),
            {"funding_rate": str(funding)},
        )
        prev_funding = D(str(md.get("previous_funding_rate", funding)))
        self._add(
            results,
            "funding_change",
            symbol,
            timeframe,
            max(D("-1"), min(D("1"), (funding - prev_funding) * D("10000"))),
            D("0.6"),
            {"funding_change": str(funding - prev_funding)},
        )
        oi = D(str(md.get("open_interest", "0")))
        prev_oi = D(str(md.get("open_interest_previous", oi)))
        oi_change = (oi - prev_oi) / prev_oi if prev_oi > 0 else D("0")
        self._add(
            results,
            "open_interest",
            symbol,
            timeframe,
            max(D("-1"), min(D("1"), oi_change * D("10"))),
            D("0.7"),
            {"oi_change": str(oi_change)},
        )
        price_change = D(str(md.get("price_change", "0")))
        divergence = D("0")
        if price_change > 0 and oi_change < 0:
            divergence = D("0.7")
        elif price_change < 0 and oi_change > 0:
            divergence = D("-0.7")
        self._add(
            results,
            "oi_divergence",
            symbol,
            timeframe,
            divergence,
            D("0.6"),
            {"price_change": str(price_change), "oi_change": str(oi_change)},
        )
        liq_pressure = D(str(md.get("liquidation_pressure", "0")))
        self._add(
            results,
            "liquidation_pressure",
            symbol,
            timeframe,
            max(D("-1"), min(D("1"), liq_pressure)),
            D("0.4"),
            {"liquidation_pressure": str(liq_pressure)},
        )
