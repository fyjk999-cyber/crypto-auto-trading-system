from datetime import datetime, timedelta, timezone

import pytest

from crypto_trader.domain.clock import SimClock, SystemClock


def test_system_clock_is_utc_aware():
    assert SystemClock().now().tzinfo is not None


def test_sim_clock_deterministic_sequence():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ticks = [t0 + timedelta(seconds=i) for i in range(3)]
    clock = SimClock(ticks)
    with pytest.raises(RuntimeError):
        clock.now()
    assert clock.step() == ticks[0]
    assert clock.now() == ticks[0]
    assert clock.step() == ticks[1]
    assert clock.step() == ticks[2]
    assert clock.step() is None
    clock.reset()
    assert clock.step() == ticks[0]
    assert clock.prev() is None
