"""Application-owned, GET-only history evidence port, with fresh service checks."""

from __future__ import annotations

import math
import time

from crypto_trader.shared_history.adapter import DATA_UNAVAILABLE, HistoricalEvidence
from crypto_trader.shared_history.readiness import FRESHNESS_THRESHOLD_SECONDS


class RuntimeHistoryConsumer:
    """No filesystem/lake access. Construction and disabled reads perform no I/O."""

    def __init__(self, evidence):
        self.evidence = evidence

    def health(self) -> HistoricalEvidence:
        if not self.evidence.enabled:
            return self.evidence.health()
        result = self.evidence.health()
        facts = result.extra
        lag = facts.get("latest_1m_freshness_seconds")
        generated = facts.get("health_snapshot_generated_at")
        valid = (
            result.available
            and facts.get("resource_state") == "NORMAL"
            and facts.get("writer_count") == 1
            and not isinstance(facts.get("writer_count"), bool)
            and facts.get("service_status") == "OK"
            and facts.get("health_snapshot_stale") is False
            and isinstance(generated, (int, float))
            and 0 <= time.time() * 1000 - generated <= 60_000
            and not isinstance(lag, bool)
            and isinstance(lag, (int, float))
            and math.isfinite(lag)
            and 0 <= lag <= FRESHNESS_THRESHOLD_SECONDS
        )
        if valid:
            return result
        return HistoricalEvidence(
            available=False,
            status=DATA_UNAVAILABLE,
            dataset="health",
            symbol="",
            timeframe=None,
            reason="HISTORICAL_DATA_UNAVAILABLE",
            extra=facts,
        )

    def read(self, dataset: str, *args, **kwargs) -> HistoricalEvidence:
        allowed = {
            "universe",
            "metadata",
            "latest_candles",
            "historical_candles",
            "features",
            "regime",
            "funding",
            "open_interest",
        }
        if dataset not in allowed:
            raise ValueError("UNSUPPORTED_READ_ONLY_DATASET")
        health = self.health()
        if not health.available:
            return health
        return getattr(self.evidence, dataset)(*args, **kwargs)
