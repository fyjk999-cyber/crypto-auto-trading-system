"""OKX DEMO-only execution bridge. Never LIVE."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_trader.exchange.okx import OKXAdapter


@dataclass
class DemoOrderResult:
    accepted: bool
    demo: bool
    exchange_order_id: str | None = None
    reason: str = ""


class DemoExecutor:
    def __init__(self, adapter: OKXAdapter | None = None) -> None:
        self.adapter = adapter or OKXAdapter(demo=True)

    async def submit(self, order) -> DemoOrderResult:
        if not self.adapter.demo:
            return DemoOrderResult(False, False, reason="LIVE_FORBIDDEN")
        try:
            normalized = await self.adapter.submit_order(order)
            return DemoOrderResult(True, True, normalized.exchange_order_id)
        except Exception as exc:
            return DemoOrderResult(False, True, reason=type(exc).__name__)
