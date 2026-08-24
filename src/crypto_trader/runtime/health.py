from __future__ import annotations

from datetime import datetime, timezone

from crypto_trader.domain.enums import HealthStatus


class HealthRegistry:
    def __init__(self) -> None:
        self.components: dict[str, dict] = {}

    def set(self, name: str, ok: bool, detail: str = "") -> None:
        self.components[name] = {
            "ok": ok,
            "detail": detail,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def overall(self) -> HealthStatus:
        values = [c["ok"] for c in self.components.values()]
        if not values:
            return HealthStatus.UNHEALTHY
        if all(values):
            return HealthStatus.OK
        return HealthStatus.UNHEALTHY

    def snapshot(self) -> dict:
        return {"overall": self.overall().value, "components": self.components}
