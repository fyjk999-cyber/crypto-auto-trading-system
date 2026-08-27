from datetime import UTC, datetime

from crypto_trader.evolution.hierarchical.coordinator import RuntimeReviewCoordinator


class FakeJobStore:
    def __init__(self):
        self.rows = {}

    async def get(self, key):
        return self.rows.get(key)

    async def put(self, key, review_id, period_type, period_id, status, error=""):
        self.rows[key] = {
            "status": status,
            "period_type": period_type,
            "period_id": period_id,
            "review_id": review_id,
        }


async def test_coordinator_runs_daily_and_idempotent():
    store = FakeJobStore()
    coordinator = RuntimeReviewCoordinator(store)
    now = datetime(2026, 8, 26, 0, 5, 0, tzinfo=UTC)
    calls = []
    first = await coordinator.run_due(now, {"DAILY": lambda period: calls.append(period.period_id)})
    second = await coordinator.run_due(
        now, {"DAILY": lambda period: calls.append(period.period_id)}
    )
    assert first[0]["status"] == "COMPLETED"
    assert second[0]["status"] == "SKIPPED_DONE"
    assert calls == ["2026-08-25"]


async def test_coordinator_serial_order_on_monday_month_year():
    store = FakeJobStore()
    coordinator = RuntimeReviewCoordinator(store)
    now = datetime(2026, 1, 1, 0, 5, 0, tzinfo=UTC)  # Thursday, Jan 1
    order = []
    callbacks = {
        p: lambda period, p=p: order.append(p) for p in ["DAILY", "WEEKLY", "MONTHLY", "YEARLY"]
    }
    await coordinator.run_due(now, callbacks)
    # Jan 1 2026 is Thursday, not Monday; weekly should not fire. But monthly/yearly do.
    assert order[0] == "DAILY"
    assert "MONTHLY" in order
    assert "YEARLY" in order
    assert "WEEKLY" not in order
