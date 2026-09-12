"""Shadow runtime isolation proof (directive §7 / §8 / §9) — assertions only.

The static tests (``test_I13`` / ``test_I13b``) prove the shadow package
contains no market-producer or provider reference. Necessary, but not
sufficient: they cannot prove that *enabling* shadow adds zero runtime provider
traffic, nor that the consumer cannot starve the real trading loops.

This module asserts on measurements produced by
``tests/integration/_shadow_isolation_probe.py``, which runs in a SEPARATE
interpreter. That split is deliberate: the probe creates real asyncio load
(10,000 observations, saturated loop, deadline schedulers), and running it
in-process left background tasks alive that perturbed unrelated tests depending
on collection order. A flaky test that breaks other tests is worse than no test,
so the load-bearing work is isolated in its own process and only the verdicts
are asserted here.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

import pytest

PROBE = pathlib.Path(__file__).with_name("_shadow_isolation_probe.py")
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def isolation_report() -> dict:
    out = pathlib.Path(tempfile.mkdtemp()) / "shadow_isolation.json"
    completed = subprocess.run(
        [sys.executable, str(PROBE), str(out)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, (
        f"probe failed rc={completed.returncode}\n"
        f"stdout={completed.stdout[-2000:]}\nstderr={completed.stderr[-2000:]}"
    )
    assert out.exists(), "probe produced no report"
    return json.loads(out.read_text())


# ------------------------------------------------------------ §7 provider delta


def test_shadow_enabling_adds_zero_provider_requests(isolation_report):
    """MODE A (disabled) vs MODE B/C (enabled): provider exits must be identical.

    Counted at the feed's real network exits, at CLASS level, so an indirect
    call made by shadow would be visible here even though grep cannot see it.
    """
    a = isolation_report["A"]["provider_requests"]
    b = isolation_report["B_100"]["provider_requests"]
    c = isolation_report["C_SATURATION"]["provider_requests"]
    assert b - a == 0, f"shadow added provider requests: A={a} B={b}"
    assert c - a == 0, f"shadow added provider requests under saturation: A={a} C={c}"


def test_provider_delta_is_not_vacuous(isolation_report):
    """Guard against a hollow proof: the counter must have been armed.

    If instrumentation silently failed, every mode would report 0 and the delta
    test above would pass for the wrong reason. A non-empty breakdown of
    instrumented feed methods fails loudly instead.
    """
    breakdown = isolation_report["A"]["provider_breakdown"]
    assert breakdown, "provider counter was never armed - delta proof would be hollow"


# ------------------------------------------------------------ §8 event loop lag


def test_event_loop_lag_bounded_in_all_three_modes(isolation_report):
    for key in ("A", "B_100", "C_SATURATION"):
        lag = isolation_report[key]["event_loop_lag"]
        assert lag["samples"] > 0
        assert lag["max"] < 250.0, f"{key} lag max {lag['max']}ms indicates blocking"
        assert lag["p99"] < 100.0, f"{key} lag p99 {lag['p99']}ms"


def test_shadow_does_not_increase_lag_pathologically(isolation_report):
    """A sidecar may cost something, but must not multiply the loop latency."""
    a = isolation_report["A"]["event_loop_lag"]["median"]
    b = isolation_report["B_100"]["event_loop_lag"]["median"]
    c = isolation_report["C_SATURATION"]["event_loop_lag"]["median"]
    assert b < max(a, 0.5) + 5.0, f"lag median A={a} B={b}"
    assert c < max(a, 0.5) + 5.0, f"lag median A={a} C={c}"


def test_no_scheduler_starvation_under_saturation(isolation_report):
    """POSITION_REVIEW / MARKET_SCAN / RECONCILIATION starvation must be NO."""
    schedulers = isolation_report["schedulers"]
    assert schedulers["position_review"]["runs"] > 0
    assert schedulers["market_scan"]["runs"] > 0
    assert schedulers["reconciliation"]["runs"] > 0
    assert schedulers["position_review"]["misses"] == 0, "position review starved"
    assert schedulers["market_scan"]["misses"] == 0, "market scan starved"
    assert schedulers["reconciliation"]["misses"] == 0, "reconciliation starved"


# ------------------------------------------------------------ §9 tap cost


def test_tap_synchronous_cost_stays_sidecar_scale(isolation_report):
    """Publish the real tap cost; must stay sub-millisecond at the median.

    This is the synchronous part that runs on the trading thread. Persistence
    happens on the sidecar consumer and is not on the decision path.
    """
    cost = isolation_report["C_SATURATION"]["tap_cost_ms"]
    assert cost["samples"] >= 10_000
    assert cost["median"] < 1.0, f"tap median cost {cost['median']}ms"
    assert cost["p99"] < 5.0, f"tap p99 cost {cost['p99']}ms"


def test_tap_cost_is_linear_not_quadratic(isolation_report):
    """10k observations must not degrade per-observation cost vs 100."""
    small = isolation_report["B_100"]["tap_cost_ms"]["median"]
    large = isolation_report["C_SATURATION"]["tap_cost_ms"]["median"]
    assert large < max(small, 0.05) * 10, (
        f"per-observation cost grew from {small}ms to {large}ms"
    )
