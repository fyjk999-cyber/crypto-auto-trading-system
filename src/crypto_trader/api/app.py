"""FastAPI control plane. Routes are thin: validation/auth/service/response only."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, WebSocket
from pydantic import BaseModel
from sqlalchemy import text

from crypto_trader.api.deps import AppState
from crypto_trader.config import get_settings
from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import SignalIntent
from crypto_trader.risk.engine import RiskEngine


class KillSwitchBody(BaseModel):
    enabled: bool
    reason: str = "manual API"


class ManualOrderBody(BaseModel):
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: str
    price: str | None = None


def serialize_order(order) -> dict:
    return order.model_dump(mode="json")


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title="Crypto Automated Trading System", version="0.1.0")
    app.state.ctx = state

    def ctx() -> AppState:
        return state

    @app.get("/health")
    async def health():
        snapshot = (
            state.engine.health.snapshot()
            if state.engine
            else {
                "overall": "OK",
                "components": {
                    "api": {"ok": True, "detail": "", "checked_at": datetime.now(UTC).isoformat()}
                },
            }
        )
        return snapshot

    @app.get("/ready")
    async def ready():
        try:
            async with state.database.session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"database not ready: {exc}") from exc
        return {"ready": True, "mode": state.settings.effective_mode().value}

    @app.get("/version")
    async def version():
        import os

        return {
            "git_sha": os.environ.get("GIT_SHA", "0dc4884ae3e416dc1df22f96620f55e8e4f41734"),
            "api_version": "v1",
            "schema_version": "1",
            "deployment_id": os.environ.get("DEPLOYMENT_ID", "local"),
            "environment": state.settings.app_env,
            "build_timestamp": os.environ.get("BUILD_TIMESTAMP", ""),
        }

    @app.get("/cloud-status")
    async def cloud_status():
        return {
            "status": "OK",
            "environment": state.settings.app_env,
            "trading_mode": state.settings.effective_mode().value,
            "live_trading_enabled": state.settings.live_trading_enabled,
        }

    @app.get("/runtime")
    async def runtime():
        if state.engine is None:
            return {"engine": "not attached"}
        return state.engine.runtime_snapshot()

    @app.get("/orders")
    async def orders(limit: int = 200):
        return [serialize_order(o) for o in await state.order_manager.list_all(limit=limit)]

    @app.get("/orders/{order_id}")
    async def order(order_id: str):
        order = await state.order_manager.get(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="order not found")
        events = await state.order_manager.list_events(order_id)
        return {
            "order": serialize_order(order),
            "events": [e.model_dump(mode="json") for e in events],
        }

    @app.get("/positions")
    async def positions():
        positions = await state.portfolio.get_positions()
        return {symbol: pos.model_dump(mode="json") for symbol, pos in positions.items()}

    @app.get("/account")
    async def account():
        account = await state.portfolio.get_account(state.settings.effective_mode())
        return account.model_dump(mode="json")

    @app.get("/ledger")
    async def ledger(limit: int = 200):
        entries = await state.ledger.list_entries_recent(limit=limit)
        return [e.model_dump(mode="json") for e in entries]

    @app.get("/audit")
    async def audit(limit: int = 100):
        rows = await state.audit.list_recent(limit=limit)
        return [
            {
                "audit_event_id": r.audit_event_id,
                "event_id": r.event_id,
                "run_id": r.run_id,
                "action": r.action,
                "actor": r.actor,
                "target": r.target,
                "order_id": r.order_id,
                "client_order_id": r.client_order_id,
                "exchange_order_id": r.exchange_order_id,
                "before": r.before_json,
                "after": r.after_json,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            }
            for r in rows
        ]

    @app.get("/killswitch")
    async def killswitch():
        return state.risk.kill_switch.snapshot()

    @app.post("/killswitch", dependencies=[Depends(lambda: None)])
    async def set_killswitch(body: KillSwitchBody):
        if body.enabled:
            state.risk.kill_switch.engage(body.reason)
        else:
            state.risk.kill_switch.disengage(body.reason)
        await state.audit.log(
            "KILL_SWITCH", target="global", actor="api", after=state.risk.kill_switch.snapshot()
        )
        return state.risk.kill_switch.snapshot()

    @app.post("/manual-orders")
    async def manual_order(body: ManualOrderBody):
        """Manual order entry through the same core path (authority + engine required)."""
        if state.engine is None:
            raise HTTPException(status_code=409, detail="engine not running")
        existing = await state.order_manager.get_by_client(body.client_order_id)
        if existing is not None:
            return {"idempotent": True, "order": serialize_order(existing)}
        # Run the exact same core pipeline as a strategy signal
        signal = SignalIntent(
            signal_id=body.client_order_id,
            strategy_id="manual_api",
            symbol=body.symbol,
            side=body.side,
            quantity=body.quantity,
            limit_price=body.price,
        )
        decision = await state.engine.process_signal(signal)
        if decision is not None and decision.decision.value != "APPROVE":
            return {"decision": decision.model_dump(mode="json")}
        return {"decision": "APPROVE", "client_order_id": body.client_order_id}

    @app.websocket("/ws")
    async def websocket_events(websocket: WebSocket):
        await websocket.accept()
        while True:
            await websocket.send_json(
                {
                    "event_type": "runtime",
                    "event_version": "v1",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "payload": {
                        "state": state.engine.state_machine.state.value
                        if state.engine
                        else "STOPPED",
                        "mode": state.settings.effective_mode().value,
                    },
                }
            )
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            except TimeoutError:
                continue

    return app


def build_default_app():
    """Build an app with a default paper-trading state (no engine)."""
    settings = get_settings()
    from crypto_trader.persistence.database import Database

    database = Database(settings.database_url)
    state = AppState(
        settings=settings,
        database=database,
        order_manager=__import__(
            "crypto_trader.order.manager", fromlist=["OrderManager"]
        ).OrderManager(database.session_factory),
        ledger=__import__("crypto_trader.ledger.service", fromlist=["LedgerService"]).LedgerService(
            database.session_factory
        ),
        portfolio=__import__(
            "crypto_trader.portfolio.service", fromlist=["PortfolioService"]
        ).PortfolioService(database.session_factory),
        audit=__import__(
            "crypto_trader.observability.audit", fromlist=["AuditService"]
        ).AuditService(database.session_factory),
        risk=RiskEngine(),
        market_data=__import__(
            "crypto_trader.market_data.service", fromlist=["MarketDataService"]
        ).MarketDataService(),
        leases=__import__("crypto_trader.runtime.lease", fromlist=["LeaseManager"]).LeaseManager(
            database.session_factory
        ),
        reconciliation=__import__(
            "crypto_trader.reconciliation.service", fromlist=["ReconciliationService"]
        ).ReconciliationService(database.session_factory),
    )
    return create_app(state)


app = build_default_app()
