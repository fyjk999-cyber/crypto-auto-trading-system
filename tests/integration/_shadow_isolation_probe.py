"""Shadow sidecar isolation probe — run in a SUBPROCESS, prints JSON.

Why a subprocess
----------------
The heavy isolation measurements (10,000 observations, saturated event loop,
deadline schedulers) create real asyncio load. Running them inside the shared
pytest process left background tasks alive and perturbed *unrelated* tests
(`test_research_attention_authority`, `test_engine_authority_end_to_end`)
depending on collection order.

A flaky test that breaks other tests is worse than no test, so the measurement
runs in its own interpreter: it cannot touch the parent's event loop, and its
result is parsed as JSON. The assertions stay in the pytest file.

Invoked as: ``python -m tests.integration._shadow_isolation_probe``
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from datetime import UTC, datetime
from decimal import Decimal

FEED_REFRESH_METHODS = (
    "_refresh_ticker",
    "_refresh_book",
    "_refresh_mark",
    "_refresh_index",
    "_refresh_funding",
    "_refresh_oi",
)
SYMBOL = "BTCUSDT"


def _observation(index: int):
    from crypto_trader.shadow.tap import ShadowObservation

    return ShadowObservation(
        decision_id=f"dec_{index}",
        symbol=SYMBOL,
        action="NO_TRADE",
        reason_codes=["SIGNAL_TOO_WEAK"],
        thesis="abstention",
        market_data_quality="GOOD",
        reference_price=Decimal("100"),
        market_regime="RANGE",
        decided_at=datetime.now(UTC),
    )


class ProviderRequestCounter:
    """Counts every OKX public-feed network exit, at class level.

    Patching the class (not an instance) means feeds created indirectly by code
    under test are counted too, so an invisible indirect call cannot hide.
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self._originals: dict[str, object] = {}
        self._cls = None

    def __enter__(self):
        from crypto_trader.market_data.okx_public_feed import OKXPublicMarketFeed

        self._cls = OKXPublicMarketFeed
        for name in FEED_REFRESH_METHODS:
            original = getattr(OKXPublicMarketFeed, name, None)
            if original is None or not callable(original):
                continue
            self._originals[name] = original
            self.counts[name] = 0

            def wrapper(feed, *args, _n=name, _o=original, **kwargs):
                self.counts[_n] = self.counts.get(_n, 0) + 1
                return _o(feed, *args, **kwargs)

            setattr(OKXPublicMarketFeed, name, wrapper)
        return self

    def __exit__(self, *exc):
        for name, original in self._originals.items():
            setattr(self._cls, name, original)
        return False

    @property
    def total(self) -> int:
        return sum(self.counts.values())


class DeadlineScheduler:
    """Stand-in for a real trading loop: counts missed deadlines."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.runs = 0
        self.misses = 0
        self._task: asyncio.Task | None = None
        self._stop = False

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_at = loop.time() + self.interval
        while not self._stop:
            await asyncio.sleep(max(0.0, next_at - loop.time()))
            now = loop.time()
            self.runs += 1
            if now > next_at + self.interval:
                self.misses += 1
            next_at += self.interval

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


async def _measure_lag(duration: float, *, sample_interval: float = 0.002) -> list[float]:
    lag: list[float] = []
    loop = asyncio.get_running_loop()
    end = loop.time() + duration
    while loop.time() < end:
        expected = loop.time() + sample_interval
        await asyncio.sleep(sample_interval)
        lag.append(max(0.0, (loop.time() - expected) * 1000.0))
    return lag


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))]


def _summarise(lag: list[float]) -> dict:
    return {
        "median": round(statistics.median(lag), 3) if lag else 0.0,
        "p95": round(_percentile(lag, 95), 3),
        "p99": round(_percentile(lag, 99), 3),
        "max": round(max(lag), 3) if lag else 0.0,
        "samples": len(lag),
    }


async def _run_mode(*, mode: str, observations: int, duration: float) -> dict:
    """MODE A = shadow disabled; B/C = enabled with the given observation load."""
    from crypto_trader.shadow.candidate_store import ShadowCandidateStore
    from crypto_trader.shadow.tap import ShadowDecisionTap

    tap = None
    seen: list[float] = []
    result = {"mode": mode, "observations": observations}
    with ProviderRequestCounter() as record_requests:
        if mode != "A":
            store = ShadowCandidateStore(_session_factory())
            tap = ShadowDecisionTap(store=store)
            for index in range(observations):
                import time

                started = time.perf_counter()
                tap.observe(_observation(index))
                seen.append((time.perf_counter() - started) * 1000.0)
                if index % 64 == 0:
                    # Give the sidecar consumer a chance to run, exactly like the
                    # production loop yields between ticks.
                    await asyncio.sleep(0)
        lag = await _measure_lag(duration)
        result["provider_requests"] = record_requests.total
        result["provider_breakdown"] = dict(record_requests.counts)
    if seen:
        result["tap_cost_ms"] = {
            "median": round(statistics.median(seen), 4),
            "p95": round(_percentile(seen, 95), 4),
            "p99": round(_percentile(seen, 99), 4),
            "max": round(max(seen), 4),
            "samples": len(seen),
        }
    result["event_loop_lag"] = _summarise(lag)
    return result


async def _schedulers_under_saturation() -> dict:
    """Position review / market scan / reconciliation cadences vs 10k observations."""
    from crypto_trader.shadow.candidate_store import ShadowCandidateStore
    from crypto_trader.shadow.tap import ShadowDecisionTap

    store = ShadowCandidateStore(_session_factory())
    tap = ShadowDecisionTap(store=store)
    reviews = DeadlineScheduler(0.02)
    scans = DeadlineScheduler(0.05)
    reconciliations = DeadlineScheduler(0.1)
    for scheduler in (reviews, scans, reconciliations):
        scheduler.start()
    try:
        for index in range(10_000):
            tap.observe(_observation(index))
            if index % 32 == 0:
                await asyncio.sleep(0)
        await asyncio.sleep(0.4)
    finally:
        for scheduler in (reviews, scans, reconciliations):
            await scheduler.stop()
    return {
        "position_review": {"runs": reviews.runs, "misses": reviews.misses},
        "market_scan": {"runs": scans.runs, "misses": scans.misses},
        "reconciliation": {"runs": reconciliations.runs, "misses": reconciliations.misses},
    }


async def main() -> dict:
    out: dict = {}
    out["A"] = await _run_mode(mode="A", observations=0, duration=0.5)
    out["B_100"] = await _run_mode(mode="B", observations=100, duration=0.5)
    out["C_SATURATION"] = await _run_mode(mode="C", observations=10_000, duration=0.8)
    out["schedulers"] = await _schedulers_under_saturation()
    return out


def _session_factory():
    from crypto_trader.persistence.database import Database

    db = Database("sqlite+aiosqlite:///:memory:")
    return db.session_factory


if __name__ == "__main__":
    import pathlib
    import tempfile

    payload = asyncio.run(main())
    path = sys.argv[1] if len(sys.argv) > 1 else str(
        pathlib.Path(tempfile.gettempdir()) / "shadow_isolation_probe.json"
    )
    pathlib.Path(path).write_text(json.dumps(payload, indent=2))
    print(json.dumps({"probe": "ok", "path": path}))
