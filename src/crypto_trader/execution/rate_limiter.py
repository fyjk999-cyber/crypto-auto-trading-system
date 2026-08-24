from __future__ import annotations

import time


class RateLimiter:
    """Token bucket rate-limit budget shared by submission paths."""

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self.tokens = float(capacity)
        self.updated = time.monotonic()

    def allow(self, cost: int = 1) -> bool:
        now = time.monotonic()
        self.tokens = min(float(self.capacity), self.tokens + (now - self.updated) * self.refill_per_second)
        self.updated = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False
