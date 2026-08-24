"""FastAPI control plane. Routes are thin: validation/auth/service/response only."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, WebSocket
from pydantic import BaseModel
from sqlalchemy import text

from crypto_trader.api.deps import AppState
from crypto_trader.config import get_settings
from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import SignalIntent
from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.perpetual.domain import PerpetualContract, PositionSide
from crypto_trader.perpetual.engine import PerpetualPaperEngine
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
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if state.engine is not None:
            await state.engine.start()
        yield
        if state.engine is not None:
            await state.engine.stop()

    app = FastAPI(title="Crypto Automated Trading System", version="0.1.0", lifespan=lifespan)
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

    def _alpha_from_state():
        if state.engine is None:
            return None
        for strategy in state.engine.strategies:
            if getattr(strategy, "name", None) == "multi_strategy_alpha":
                return strategy
        return None

    def _perpetual_engine():
        contract = PerpetualContract(
            symbol="BTCUSDT_PERP",
            base="BTC",
            quote="USDT",
            settlement_asset="USDT",
            max_leverage=Decimal("6"),
            taker_fee_rate=Decimal("0.0005"),
        )
        return PerpetualPaperEngine(state.database.session_factory, contract)

    @app.post("/paper/perpetual/open")
    async def paper_perpetual_open(body: dict):
        engine = _perpetual_engine()
        side = PositionSide(body["side"])
        pos = await engine.open_position(
            side,
            Decimal(body.get("quantity", "0.1")),
            Decimal(body.get("price", "100")),
            Decimal(body.get("leverage", "3")),
        )
        return pos.model_dump(mode="json")

    @app.post("/paper/perpetual/close")
    async def paper_perpetual_close(body: dict):
        engine = _perpetual_engine()
        side = PositionSide(body["side"])
        pos = await engine.close_position(
            side, Decimal(body.get("quantity", "0.1")), Decimal(body.get("price", "100"))
        )
        return pos.model_dump(mode="json") if pos else {"closed": True}

    @app.get("/paper/perpetual/positions")
    async def paper_perpetual_positions():
        engine = _perpetual_engine()
        state = await engine.load_state()
        return {"positions": {k: v.model_dump(mode="json") for k, v in state.positions.items()}}

    @app.get("/market")
    async def market():
        adapter = getattr(state.engine, "adapter", None) if state.engine else None
        get_market_state = getattr(adapter, "get_market_state", None)
        if get_market_state is not None:
            try:
                ms = await get_market_state("BTCUSDT")
                return ms.model_dump(mode="json")
            except Exception as exc:
                return {"status": "UNAVAILABLE", "error": str(exc)}
        return {
            "symbol": "BTCUSDT",
            "status": "SYNTHETIC",
            "data_source": "PAPER_SYNTHETIC",
            "funding_rate": None,
            "open_interest": None,
            "basis": None,
        }

    @app.get("/market/sources")
    async def market_sources():
        adapter = getattr(state.engine, "adapter", None) if state.engine else None
        get_market_state = getattr(adapter, "get_market_state", None)
        if get_market_state is not None:
            try:
                ms = await get_market_state("BTCUSDT")
                return {k: v.model_dump(mode="json") for k, v in ms.sources.items()}
            except Exception as exc:
                return {"status": "UNAVAILABLE", "error": str(exc)}
        return {"status": "SYNTHETIC", "sources": {}}

    @app.get("/regime")
    async def regime():
        alpha = _alpha_from_state()
        if alpha is None or alpha.last_meta is None:
            return {"status": "NO_DATA", "regime": None, "reasons": []}
        return {
            "status": "OK",
            "regime": alpha.last_meta.regime,
            "confidence": str(alpha.last_meta.confidence),
            "reasons": alpha.last_meta.reason_codes,
        }

    @app.get("/signals")
    async def signals(limit: int = 50):
        alpha = _alpha_from_state()
        if alpha is None or alpha.last_meta is None:
            return {"signals": []}
        return {
            "signals": [
                {
                    "symbol": alpha.last_meta.symbol,
                    "side": alpha.last_meta.side.value,
                    "confidence": str(alpha.last_meta.confidence),
                    "reasons": alpha.last_meta.reason_codes,
                    "regime": alpha.last_meta.regime,
                }
            ],
            "count": 1,
        }

    @app.get("/strategies")
    async def strategies():
        if state.engine is None:
            return {"strategies": []}
        return {
            "strategies": [{"name": s.name, "version": s.version} for s in state.engine.strategies]
        }

    @app.get("/risk")
    async def risk():
        return {
            "trading_mode": state.settings.effective_mode().value,
            "live_trading_enabled": state.settings.live_trading_enabled,
            "kill_switch": state.risk.kill_switch.snapshot(),
            "risk_config": state.risk.config.model_dump(mode="json"),
        }

    @app.get("/margin")
    async def margin():
        account = await state.portfolio.get_account(state.settings.effective_mode())
        positions = await state.portfolio.get_positions()
        return {
            "equity": str(account.equity),
            "balances": {k: v.model_dump(mode="json") for k, v in account.balances.items()},
            "positions": {k: v.model_dump(mode="json") for k, v in positions.items()},
        }

    @app.get("/reviews")
    async def reviews(limit: int = 50):
        # Structured reviews are emitted by governance runtime; persisted
        # review storage is not yet implemented, so this is intentionally empty.
        return {"reviews": [], "count": 0}

    @app.get("/stress-tests")
    async def stress_tests(limit: int = 50):
        return {"stress_tests": [], "count": 0}

    @app.get("/daily-reviews")
    async def daily_reviews(limit: int = 50):
        persistence = MemoryPersistence(state.database.session_factory)
        rows = await persistence.load_daily_reviews(limit=limit)
        return {"daily_reviews": rows, "count": len(rows)}

    @app.get("/learning")
    async def learning():
        alpha = _alpha_from_state()
        if alpha is None:
            return {"status": "NO_ALPHA", "fast_learning": {}}
        return {
            "status": "OK",
            "fast_learning": alpha.fast_learning.snapshot(),
            "slow_learning_candidates": list(alpha.slow_learning.candidates.keys()),
        }

    @app.get("/exchange-health")
    async def exchange_health():
        adapter_connected = (
            getattr(state.engine, "adapter", None).connected if state.engine else False
        )
        return {
            "adapter": "connected" if adapter_connected else "disconnected",
            "mode": state.settings.effective_mode().value,
            "paper_mode": state.settings.paper_mode,
        }

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

    @app.get("/internal/runtime-health")
    async def internal_runtime_health():
        if state.supervisor is not None:
            return state.supervisor.health()
        if state.engine is not None:
            return state.engine.runtime_snapshot()
        return {"runtime_state": "NOT_RUNNING", "instance_id": "none"}

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
        queue: asyncio.Queue = asyncio.Queue()
        if state.engine is not None:
            state.engine.event_bus.subscribe("*", lambda event: queue.put_nowait(event))
        while True:
            event = None
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5.0)
            except TimeoutError:
                event = None
            if event is None:
                payload = {
                    "state": state.engine.state_machine.state.value if state.engine else "STOPPED",
                    "mode": state.settings.effective_mode().value,
                }
                envelope = {
                    "event_type": "runtime",
                    "event_version": "v1",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "payload": payload,
                }
            else:
                envelope = {
                    "event_type": "runtime",
                    "event_version": "v1",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "payload": str(event),
                }
            await websocket.send_json(envelope)
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
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
