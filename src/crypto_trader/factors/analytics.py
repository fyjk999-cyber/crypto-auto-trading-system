"""Factor analytics: read-only aggregation for LLM/research."""

from __future__ import annotations

from crypto_trader.factors.models import FactorPerformance


class FactorAnalytics:
    def summarize(self, performances: list[FactorPerformance]) -> dict:
        out = {}
        for perf in performances:
            out[perf.factor_name] = {
                "sample_size": perf.sample_size,
                "win_rate": str(perf.win_rate),
                "sharpe": str(perf.sharpe),
                "status": _status(perf),
            }
        return out


def _status(perf: FactorPerformance) -> str:
    if perf.sample_size < 30:
        return "EXPERIMENTAL"
    if perf.sharpe < 0.2 or perf.win_rate < 0.45:
        return "DEGRADING"
    if perf.win_rate < 0.52:
        return "TESTING"
    return "HEALTHY"
