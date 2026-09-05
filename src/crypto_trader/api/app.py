"""FastAPI control plane. Routes are thin: validation/auth/service/response only."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from crypto_trader.api.deps import AppState
from crypto_trader.config import get_settings
from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import SignalIntent
from crypto_trader.exchange.okx import OKXAdapter, OKXDiagnosticError
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.exposure.service import ExposureService
from crypto_trader.factors.service import FactorService
from crypto_trader.governance.factual_learning import FactualEpisodeLearning
from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.intelligence.feedback.interface import ResearchFeedbackInterface
from crypto_trader.okx_vault.client import BrokerClient
from crypto_trader.perpetual.domain import PerpetualContract, PositionSide
from crypto_trader.perpetual.engine import PerpetualPaperEngine
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.security.auth import Role, require_role_dependency


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


def serialize_position(position) -> dict:
    """Serialize a position with the same canonical exposure used by Risk."""

    payload = position.model_dump(mode="json")
    exposure = ExposureService.for_position(position)
    payload["gross_notional"] = str(exposure.gross_notional)
    payload["signed_notional"] = str(exposure.signed_notional)
    return payload


def create_app(state: AppState) -> FastAPI:
    okx_broker = BrokerClient()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if state.engine is not None:
            await state.engine.start()
        if state.supervisor is not None:
            await state.supervisor.start(run_id=state.engine.run_id if state.engine else None)
        # Provider reachability is observability only.  A failed probe leaves
        # the PAPER runtime running and must never synthesize a trade decision.
        await state.llm_runtime.probe()
        yield
        if state.supervisor is not None:
            await state.supervisor.stop()
        if state.engine is not None:
            await state.engine.stop()

    app = FastAPI(title="Crypto Automated Trading System", version="0.1.0", lifespan=lifespan)
    if state.settings.app_env == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.state.ctx = state
    app.state.feedback_interface = ResearchFeedbackInterface()

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

    @app.get("/llm/health")
    async def llm_health():
        return state.llm_runtime.snapshot()

    @app.get("/ready")
    async def ready():
        try:
            async with state.database.session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"database not ready: {exc}") from exc
        runtime = state.engine.runtime_snapshot() if state.engine is not None else None
        return {
            "ready": True,
            "mode": state.settings.effective_mode().value,
            "live_trading_enabled": state.settings.live_trading_enabled,
            "runtime": runtime,
        }

    def _alpha_from_state():
        if state.engine is None:
            return None
        for strategy in state.engine.strategies:
            if getattr(strategy, "name", None) == "multi_strategy_alpha":
                return strategy
            evidence_engine = getattr(strategy, "evidence_engine", None)
            if evidence_engine is not None:
                return evidence_engine
        return None

    @app.post(
        "/exchange/okx/credentials", dependencies=[Depends(require_role_dependency(Role.OPERATOR))]
    )
    async def save_okx_credentials():
        # Do not parse a secret request model: validation errors could echo input.
        raise HTTPException(status_code=403, detail="HUMAN_VAULT_CLI_REQUIRED")

    @app.get("/exchange/okx/status")
    async def okx_status():
        status = await okx_broker.credential_status()
        return {
            **state.okx_connection.snapshot(),
            **status,
            "configured": status.get("configured", False),
            "key_suffix": None,
        }

    @app.post(
        "/exchange/okx/validate", dependencies=[Depends(require_role_dependency(Role.OPERATOR))]
    )
    async def validate_okx_credentials():
        result = await okx_broker.validate_okx_demo()
        state.okx_connection.validation(result)
        return result

    @app.delete(
        "/exchange/okx/credentials", dependencies=[Depends(require_role_dependency(Role.ADMIN))]
    )
    async def delete_okx_credentials():
        raise HTTPException(status_code=403, detail="HUMAN_VAULT_CLI_REQUIRED")

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

    @app.post(
        "/paper/perpetual/open", dependencies=[Depends(require_role_dependency(Role.OPERATOR))]
    )
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

    @app.post(
        "/paper/perpetual/close", dependencies=[Depends(require_role_dependency(Role.OPERATOR))]
    )
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
                detail = str(exc)
                return {
                    "provider": "OKX_PUBLIC",
                    "source": "OKX_PUBLIC",
                    "status": "UNAVAILABLE",
                    "data_source": "REAL",
                    "last_error": detail,
                }
        if state.settings.paper_mode == "PAPER_SYNTHETIC":
            return {
                "provider": "SYNTHETIC",
                "source": "SYNTHETIC",
                "status": "SYNTHETIC",
                "data_source": "SYNTHETIC",
                "symbol": "BTCUSDT",
            }
        return {
            "provider": "OKX_PUBLIC",
            "source": "OKX_PUBLIC",
            "status": "UNAVAILABLE",
            "data_source": "REAL",
            "symbol": "BTCUSDT",
        }

    @app.get("/market/klines")
    async def market_klines(symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 500):
        interval_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}
        if interval not in interval_map:
            return {"status": "INVALID_INTERVAL", "candles": []}
        limit = max(1, min(limit, 500))
        if state.settings.kline_provider.upper() == "OKX":
            try:
                provider_symbol = SymbolMapper().to_okx(symbol.upper())
            except ValueError:
                return {
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "source": "OKX",
                    "status": "INVALID_SYMBOL",
                    "candles": [],
                }
            client = OKXAdapter(base_url=state.settings.okx_base_url)
            try:
                rows = await client.get_candles(provider_symbol, interval_map[interval], limit)
                by_open_time: dict[str, dict] = {}
                for row in rows:
                    try:
                        open_time = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC).isoformat()
                        by_open_time[open_time] = {
                            "symbol": symbol.upper(),
                            "provider_symbol": provider_symbol,
                            "interval": interval,
                            "open_time": open_time,
                            "open": str(row[1]),
                            "high": str(row[2]),
                            "low": str(row[3]),
                            "close": str(row[4]),
                            "volume": str(row[5]),
                            "closed": str(row[8]) == "1",
                            "source": "OKX",
                        }
                    except (TypeError, ValueError, IndexError) as exc:
                        raise OKXDiagnosticError(
                            "MALFORMED_RESPONSE", "OKX candle response contains invalid values"
                        ) from exc
                return {
                    "symbol": symbol.upper(),
                    "provider_symbol": provider_symbol,
                    "interval": interval,
                    "source": "OKX",
                    "status": "HEALTHY",
                    "supported_intervals": list(interval_map),
                    "candles": [by_open_time[key] for key in sorted(by_open_time)],
                }
            except OKXDiagnosticError as exc:
                return {
                    "symbol": symbol.upper(),
                    "provider_symbol": provider_symbol,
                    "interval": interval,
                    "source": "OKX",
                    "status": "UNAVAILABLE",
                    "candles": [],
                    "last_error": exc.safe_message,
                    "reason_code": exc.reason_code,
                }
            finally:
                await client.disconnect()
        return {
            "symbol": symbol.upper(),
            "interval": interval,
            "source": "OKX",
            "status": "UNAVAILABLE",
            "candles": [],
            "last_error": "Only the OKX public market-data provider is enabled",
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
                return {
                    "provider": "OKX_PUBLIC",
                    "source": "OKX_PUBLIC",
                    "status": "UNAVAILABLE",
                    "data_source": "REAL",
                    "last_error": str(exc),
                }
        if state.settings.paper_mode == "PAPER_SYNTHETIC":
            return {
                "provider": "SYNTHETIC",
                "source": "SYNTHETIC",
                "status": "SYNTHETIC",
                "data_source": "SYNTHETIC",
            }
        return {
            "provider": "OKX_PUBLIC",
            "source": "OKX_PUBLIC",
            "status": "UNAVAILABLE",
            "data_source": "REAL",
        }

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
        serialized = {symbol: serialize_position(pos) for symbol, pos in positions.items()}
        gross_exposure = sum(
            (ExposureService.for_position(pos).gross_notional for pos in positions.values()),
            Decimal("0"),
        )
        net_exposure = sum(
            (ExposureService.for_position(pos).signed_notional for pos in positions.values()),
            Decimal("0"),
        )
        return {
            "equity": str(account.equity),
            "balances": {k: v.model_dump(mode="json") for k, v in account.balances.items()},
            "positions": serialized,
            "gross_exposure": str(gross_exposure),
            "net_exposure": str(net_exposure),
        }

    @app.get("/reviews")
    async def reviews(limit: int = 50):
        rows = await FactualEpisodeLearning(state.database.session_factory).list_reviews(
            limit=limit
        )
        return {"reviews": rows, "count": len(rows)}

    @app.get("/stress-tests")
    async def stress_tests(limit: int = 50):
        return {"stress_tests": [], "count": 0}

    @app.post(
        "/dev/daily-review/run", dependencies=[Depends(require_role_dependency(Role.OPERATOR))]
    )
    async def dev_daily_review_run():
        if state.settings.app_env != "development":
            raise HTTPException(status_code=403, detail="development only")
        if state.settings.effective_mode().value != "PAPER":
            raise HTTPException(status_code=403, detail="paper only")
        scheduler = DailyReviewScheduler(
            state.database.session_factory, review_time_utc=state.settings.daily_review_time_utc
        )
        result = await scheduler.run_once()
        return result

    @app.get("/daily-reviews")
    async def daily_reviews(limit: int = 50):
        persistence = MemoryPersistence(state.database.session_factory)
        rows = await persistence.load_daily_reviews(limit=limit)
        return {"daily_reviews": rows, "count": len(rows)}

    @app.get("/learning")
    async def learning():
        alpha = _alpha_from_state()
        factual = await FactualEpisodeLearning(state.database.session_factory).snapshot()
        if alpha is None:
            return {"status": "NO_ALPHA", "fast_learning": {}, "factual": factual}
        return {
            "status": "OK",
            "fast_learning": alpha.fast_learning.snapshot(),
            "slow_learning_candidates": list(alpha.slow_learning.candidates.keys()),
            "factual": factual,
        }

    @app.get("/exchange-health")
    async def exchange_health():
        adapter_connected = (
            getattr(state.engine, "adapter", None).connected if state.engine else False
        )
        market_snapshot = await market()
        return {
            "market_data": {
                "provider": market_snapshot.get("provider", "OKX_PUBLIC"),
                "mode": "REAL" if state.settings.paper_mode == "PAPER_REAL_MARKET" else "SYNTHETIC",
                "status": market_snapshot.get("status", "UNAVAILABLE"),
            },
            "execution": {
                "provider": "OKX",
                **state.okx_connection.snapshot(),
                "status": state.okx_connection.health,
            },
            "adapter": "connected" if adapter_connected else "disconnected",
            "mode": state.settings.effective_mode().value,
            "paper_mode": state.settings.paper_mode,
        }

    @app.get("/version")
    async def version():
        import os

        return {
            "git_sha": os.environ.get("RUNNING_SHA") or os.environ.get("GIT_SHA", "unknown"),
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
        return {symbol: serialize_position(pos) for symbol, pos in positions.items()}

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

    @app.get("/api/intelligence/feedback/{symbol}")
    async def research_feedback(symbol: str):
        feedback = app.state.feedback_interface.get(symbol)
        if feedback is None:
            return {"symbol": symbol, "status": "NO_DATA"}
        return feedback

    @app.get("/api/factors/{symbol}")
    async def get_factor_snapshot(symbol: str):
        service = FactorService(state.database.session_factory)
        snapshot = await service.latest_snapshot(symbol)
        if snapshot is None:
            return {"symbol": symbol, "status": "NO_DATA", "market_state": {}}
        return snapshot

    @app.get("/api/factors/{symbol}/history")
    async def get_factor_history(symbol: str, factor: str, limit: int = 100):
        service = FactorService(state.database.session_factory)
        return await service.history(symbol, factor, limit)

    @app.get("/api/factors/{symbol}/snapshot")
    async def get_factor_market_state(symbol: str):
        service = FactorService(state.database.session_factory)
        snapshot = await service.latest_snapshot(symbol)
        if snapshot is None:
            return {"symbol": symbol, "status": "NO_DATA", "market_state": {}}
        return snapshot

    @app.get("/killswitch")
    async def killswitch():
        return state.risk.kill_switch.snapshot()

    @app.post("/killswitch", dependencies=[Depends(require_role_dependency(Role.ADMIN))])
    async def set_killswitch(body: KillSwitchBody):
        if body.enabled:
            state.risk.kill_switch.engage(body.reason)
        else:
            state.risk.kill_switch.disengage(body.reason)
        await state.audit.log(
            "KILL_SWITCH", target="global", actor="api", after=state.risk.kill_switch.snapshot()
        )
        return state.risk.kill_switch.snapshot()

    @app.post("/manual-orders", dependencies=[Depends(require_role_dependency(Role.OPERATOR))])
    async def manual_order(body: ManualOrderBody):
        """Manual order entry through the same core path (authority + engine required)."""
        if state.engine is None:
            raise HTTPException(status_code=409, detail="engine not running")
        if state.engine.enforce_llm_entry_authority:
            raise HTTPException(status_code=403, detail="NEW_DIRECTION_REQUIRES_LIVE_LLM")
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

        def _enqueue(event):
            queue.put_nowait(event)

        if state.engine is not None:
            state.engine.event_bus.subscribe("*", _enqueue)
        try:
            while True:
                event = None
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5.0)
                except TimeoutError:
                    event = None
                if event is None:
                    event_type = "runtime"
                    payload = {
                        "state": state.engine.state_machine.state.value
                        if state.engine
                        else "STOPPED",
                        "mode": state.settings.effective_mode().value,
                    }
                else:
                    event_type, payload = _envelope_from_event(event)
                envelope = {
                    "event_type": event_type,
                    "event_version": "v1",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "payload": payload,
                }
                await websocket.send_json(envelope)
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                except TimeoutError:
                    continue
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if state.engine is not None:
                state.engine.event_bus.unsubscribe(_enqueue)

    def _envelope_from_event(event):
        if isinstance(event, dict):
            return event.get("event_type", "runtime"), event.get("payload", event)
        event_type = getattr(event, "event_type", None)
        if event_type is None:
            event_type = getattr(event, "type", None)
        if event_type is None:
            event_type = "runtime"
        if hasattr(event, "model_dump"):
            payload = event.model_dump(mode="json")
        elif isinstance(event, str):
            payload = {"message": event}
        else:
            payload = repr(event)
        return str(event_type), payload

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
