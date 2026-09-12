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
        # Legacy compatibility object only. Canonical execution must always
        # pass RiskEngine and ExecutionAuthority through TradingEngine.
        return DemoOrderResult(
            False,
            bool(self.adapter.demo),
            reason="CANONICAL_ENGINE_REQUIRED",
        )
