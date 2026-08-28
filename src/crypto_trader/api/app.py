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
from crypto_trader.api.market_analysis import create_market_analysis_router
from crypto_trader.config import get_settings
from crypto_trader.credentials import EnvCredentialStore
from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import SignalIntent
from crypto_trader.exchange.binance_futures_public import (
    BinancePublicDataUnavailable,
    BinanceUSDMFuturesPublicClient,
)
from crypto_trader.exchange.okx import OKXAdapter, OKXDiagnosticError
from crypto_trader.factors.service import FactorService
from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.intelligence.feedback.interface import ResearchFeedbackInterface
from crypto_trader.llm_runtime.contracts import ModelRoute, ProviderUpsert
from crypto_trader.perpetual.domain import PerpetualContract, PositionSide
from crypto_trader.perpetual.engine import PerpetualPaperEngine
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.execution_symbols import reference_symbol_for
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


class OKXCredentialRequest(BaseModel):
    api_key: str
    api_secret: str
    api_passphrase: str
    base_url: str = "https://openapi.okx.com"
    demo: bool = True


class LLMTestRequest(BaseModel):
    provider_id: str | None = None
    provider: ProviderUpsert | None = None


class LLMRoutesRequest(BaseModel):
    routes: list[ModelRoute]


def create_app(state: AppState) -> FastAPI:
    initial_credentials = EnvCredentialStore().read()
    state.okx_connection.configure(
        initial_credentials, EnvCredentialStore.key_suffix(initial_credentials.get("OKX_API_KEY"))
    )
    okx_validation_lock = asyncio.Lock()

    async def _validate_okx_credentials(*, reuse_healthy: bool = False) -> dict:
        async with okx_validation_lock:
            if reuse_healthy and state.okx_connection.authenticated:
                return state.okx_connection.snapshot()
            values = EnvCredentialStore().read()
            if not (
                values.get("OKX_API_KEY")
                and values.get("OKX_API_SECRET")
                and values.get("OKX_API_PASSPHRASE")
            ):
                result = {
                    "authenticated": False,
                    "health": "NOT_CONFIGURED",
                    "stage": "CREDENTIALS",
                    "reason_code": "NOT_CONFIGURED",
                }
                state.okx_connection.validation(result)
                return result
            if values.get("OKX_DEMO", "true") != "true":
                result = {
                    "authenticated": False,
                    "health": "DEGRADED",
                    "stage": "CREDENTIALS",
                    "reason_code": "LIVE_FORBIDDEN",
                }
                state.okx_connection.validation(result)
                return result
            adapter = OKXAdapter(
                base_url=values.get("OKX_BASE_URL", "https://openapi.okx.com"),
                api_key=values["OKX_API_KEY"],
                api_secret=values["OKX_API_SECRET"],
                api_passphrase=values["OKX_API_PASSPHRASE"],
                demo=True,
            )
            await adapter.connect()
            stage = "PUBLIC_TIME"
            try:
                time_result = await adapter.sync_server_time()
                if abs(time_result["offset_ms"]) > 1500:
                    result = {
                        "authenticated": False,
                        "health": "DEGRADED",
                        "stage": "PUBLIC_TIME",
                        "reason_code": "TIME_OFFSET",
                    }
                    state.okx_connection.validation(result)
                    return result
                stage = "ACCOUNT_CONFIG"
                account_config = await adapter.get_account_config()
                config_rows = (
                    account_config.get("data") if isinstance(account_config, dict) else None
                )
                if (
                    not isinstance(config_rows, list)
                    or not config_rows
                    or not isinstance(config_rows[0], dict)
                ):
                    result = {
                        "authenticated": False,
                        "health": "DEGRADED",
                        "stage": "ACCOUNT_CONFIG",
                        "reason_code": "MALFORMED_RESPONSE",
                        "message": "OKX account configuration response is incomplete",
                    }
                    state.okx_connection.validation(result)
                    return result
                stage = "BALANCE"
                balances = await adapter.get_balances()
                stage = "POSITIONS"
                positions = await adapter.get_positions()
                stage = "PENDING_ORDERS"
                pending = await adapter.get_pending_orders()
                result = {
                    "authenticated": True,
                    "health": "HEALTHY",
                    "stage": "COMPLETE",
                    "reason_code": None,
                    "account_mode": config_rows[0].get("acctLv", "unknown"),
                    "position_mode": config_rows[0].get("posMode", "unknown"),
                    "instrument": "BTC-USDT-SWAP",
                    "balances": len(balances),
                    "positions": len(positions),
                    "pending_orders": len(pending.get("data", [])),
                }
                state.okx_connection.validation(result)
                return result
            except OKXDiagnosticError as exc:
                result = {
                    "authenticated": False,
                    "health": "DEGRADED",
                    "stage": stage,
                    "reason_code": exc.reason_code,
                    "exchange_code": exc.exchange_code,
                    "message": exc.safe_message,
                }
                state.okx_connection.validation(result)
                return result
            except Exception:
                result = {
                    "authenticated": False,
                    "health": "DEGRADED",
                    "stage": stage,
                    "reason_code": "VALIDATION_ERROR",
                }
                state.okx_connection.validation(result)
                return result
            finally:
                await adapter.disconnect()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        auto_validation_task = None
        daily_review_task = None
        if state.engine is not None:
            await state.engine.start()
        if state.okx_connection.configured:
            auto_validation_task = asyncio.create_task(
                _validate_okx_credentials(reuse_healthy=True), name="okx-demo-auto-validation"
            )
        if state.daily_review_scheduler is not None:
            daily_review_task = asyncio.create_task(
                state.daily_review_scheduler.loop(), name="daily-review-scheduler"
            )
        try:
            yield
        finally:
            if auto_validation_task is not None:
                if not auto_validation_task.done():
                    auto_validation_task.cancel()
                await asyncio.gather(auto_validation_task, return_exceptions=True)
            if daily_review_task is not None:
                daily_review_task.cancel()
                await asyncio.gather(daily_review_task, return_exceptions=True)
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
    app.include_router(create_market_analysis_router(state))

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

    @app.post(
        "/exchange/okx/credentials", dependencies=[Depends(require_role_dependency(Role.OPERATOR))]
    )
    async def save_okx_credentials(body: OKXCredentialRequest):
        if not body.demo:
            raise HTTPException(status_code=403, detail="LIVE is forbidden")
        store = EnvCredentialStore()
        store.write(
            {
                "OKX_API_KEY": body.api_key,
                "OKX_API_SECRET": body.api_secret,
                "OKX_API_PASSPHRASE": body.api_passphrase,
                "OKX_BASE_URL": body.base_url,
                "OKX_DEMO": "true",
            }
        )
        state.okx_connection.configure(store.read(), EnvCredentialStore.key_suffix(body.api_key))
        return {
            "saved": True,
            "demo": True,
            "key_suffix": EnvCredentialStore.key_suffix(body.api_key),
        }

    @app.get("/exchange/okx/status")
    async def okx_status():
        return state.okx_connection.snapshot()

    @app.post(
        "/exchange/okx/validate", dependencies=[Depends(require_role_dependency(Role.OPERATOR))]
    )
    async def validate_okx_credentials():
        return await _validate_okx_credentials(reuse_healthy=True)

    @app.delete(
        "/exchange/okx/credentials", dependencies=[Depends(require_role_dependency(Role.ADMIN))]
    )
    async def delete_okx_credentials():
        EnvCredentialStore().clear()
        state.okx_connection.configure({}, None)
        return state.okx_connection.snapshot()

    def _llm_gateway():
        if state.llm_gateway is None or state.llm_repository is None:
            raise HTTPException(status_code=503, detail="LLM runtime is not attached")
        return state.llm_gateway

    @app.get("/llm/status")
    async def llm_status():
        gateway = _llm_gateway()
        return {**gateway.status(), "usage": await state.llm_repository.usage_today()}

    @app.get("/llm/providers")
    async def llm_providers():
        gateway = _llm_gateway()
        return {
            "providers": [gateway.safe_provider(config) for config in gateway.providers.values()]
        }

    @app.post("/llm/providers", dependencies=[Depends(require_role_dependency(Role.OPERATOR))])
    async def create_llm_provider(body: ProviderUpsert):
        gateway = _llm_gateway()
        if body.provider_id in gateway.providers:
            raise HTTPException(status_code=409, detail="provider already exists")
        try:
            return await gateway.save_provider(body)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.put(
        "/llm/providers/{provider_id}",
        dependencies=[Depends(require_role_dependency(Role.OPERATOR))],
    )
    async def update_llm_provider(provider_id: str, body: ProviderUpsert):
        gateway = _llm_gateway()
        if provider_id != body.provider_id:
            raise HTTPException(status_code=422, detail="provider_id cannot be changed")
        try:
            return await gateway.save_provider(body)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete(
        "/llm/providers/{provider_id}",
        dependencies=[Depends(require_role_dependency(Role.ADMIN))],
    )
    async def delete_llm_provider(provider_id: str):
        gateway = _llm_gateway()
        await gateway.delete_provider(provider_id)
        return {"deleted": True, "provider_id": provider_id}

    @app.get("/llm/routes")
    async def llm_routes():
        gateway = _llm_gateway()
        return {"routes": [route.model_dump() for route in gateway.routes.values()]}

    @app.get("/llm/domain-models")
    async def llm_domain_models():
        if state.domain_model_runtime is None:
            raise HTTPException(status_code=503, detail="Domain model runtime is not attached")
        return {"domain_models": state.domain_model_runtime.describe()}

    @app.put("/llm/routes", dependencies=[Depends(require_role_dependency(Role.OPERATOR))])
    async def update_llm_routes(body: LLMRoutesRequest):
        gateway = _llm_gateway()
        try:
            routes = await gateway.save_routes(body.routes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"routes": routes}

    @app.post("/llm/test", dependencies=[Depends(require_role_dependency(Role.OPERATOR))])
    async def test_llm_provider(body: LLMTestRequest):
        if body.provider is not None:
            response = await _llm_gateway().test_unsaved_provider(body.provider)
            provider_id = body.provider.provider_id
        elif body.provider_id:
            response = await _llm_gateway().test_provider(body.provider_id)
            provider_id = body.provider_id
        else:
            raise HTTPException(status_code=422, detail="provider or provider_id is required")
        return {
            "ok": response.ok,
            "provider": response.provider or provider_id,
            "model": response.model,
            "latency_ms": round(response.latency_ms, 2),
            "checked_at": response.checked_at,
            "error_code": response.error_code.value if response.error_code else None,
        }

    @app.post("/llm/qualification", dependencies=[Depends(require_role_dependency(Role.OPERATOR))])
    async def qualify_llm_routes():
        """Run inert, schema-validated checks for the six configured routes."""
        responses = await _llm_gateway().qualify_configured_routes()
        checks = [
            {
                "route": response.route,
                "ok": response.ok,
                "provider": response.provider,
                "model": response.model,
                "latency_ms": round(response.latency_ms, 2),
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "total_tokens": response.total_tokens,
                "error_code": response.error_code.value if response.error_code else None,
            }
            for response in responses
        ]
        return {"ok": bool(checks) and all(check["ok"] for check in checks), "checks": checks}

    @app.get("/llm/usage")
    async def llm_usage():
        _llm_gateway()
        return await state.llm_repository.usage_today()

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
                payload = ms.model_dump(mode="json")
                payload.update(
                    provider="OKX", source="OKX", status=ms.health.value, data_source="REAL"
                )
                return payload
            except Exception as exc:
                detail = str(exc)
                return {
                    "provider": "OKX",
                    "source": "OKX",
                    "status": "GEO_RESTRICTED"
                    if "451" in detail or "restricted" in detail.lower()
                    else "UNAVAILABLE",
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
            "provider": "OKX",
            "source": "OKX",
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
            provider_symbol = "BTC-USDT-SWAP" if symbol.upper() == "BTCUSDT" else symbol.upper()
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
        client = BinanceUSDMFuturesPublicClient()
        try:
            raw = await client.get_klines(symbol, interval=interval, limit=limit)
            candles = BinanceUSDMFuturesPublicClient.normalize_kline_array(raw, symbol, interval)
            return {
                "symbol": symbol,
                "interval": interval,
                "source": "BINANCE_USDM",
                "status": "HEALTHY",
                "candles": candles,
            }
        except BinancePublicDataUnavailable as exc:
            status = (
                "GEO_RESTRICTED"
                if ("451" in str(exc) or "restricted" in str(exc).lower())
                else "UNAVAILABLE"
            )
            return {
                "symbol": symbol,
                "interval": interval,
                "source": "BINANCE_USDM",
                "status": status,
                "candles": [],
                "last_error": str(exc),
            }
        finally:
            await client.close()

    @app.get("/market/sources")
    async def market_sources():
        adapter = getattr(state.engine, "adapter", None) if state.engine else None
        get_market_state = getattr(adapter, "get_market_state", None)
        if get_market_state is not None:
            try:
                ms = await get_market_state("BTCUSDT")
                return {
                    "provider": "OKX",
                    "source": "OKX",
                    "status": ms.health.value,
                    "data_source": "REAL",
                    "sources": {k: v.model_dump(mode="json") for k, v in ms.sources.items()},
                }
            except Exception as exc:
                return {
                    "provider": "OKX",
                    "source": "OKX",
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
            "provider": "OKX",
            "source": "OKX",
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

    @app.get("/exploration/status")
    async def exploration_status_endpoint():
        """Read-only PAPER exploration learning-coverage report.

        Aggregates decision evidence (incl. rejected opportunities and
        not-sampled counterfactuals) and completed-trade outcomes into the
        exploration-stage coverage and calibration metrics. Never fabricates:
        buckets fill as real PAPER trades accumulate.
        """
        from crypto_trader.runtime.exploration_analytics import exploration_status

        return await exploration_status(
            state.database.session_factory, get_settings()
        )

    @app.get("/decision-context")
    async def decision_context():
        """Read-only latest Live decision context (real persisted evidence).

        Surfaces the strategy-selection philosophy to the frontend: dominant
        strategy, fit, supporting/contradicting factors, confidence. Values
        come from the newest llm_chief_trader DecisionEvidence row; when none
        exists the endpoint reports NOT_AVAILABLE rather than fabricating.
        """
        from sqlalchemy import select

        from crypto_trader.persistence.models import DecisionEvidenceORM

        async with state.database.session_factory() as session:
            row = (
                await session.execute(
                    select(DecisionEvidenceORM)
                    .where(DecisionEvidenceORM.strategy_id == "llm_chief_trader")
                    .order_by(DecisionEvidenceORM.timestamp_utc.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if row is None:
            return {"status": "NOT_AVAILABLE"}
        evidence = row.analysis_evidence_json or {}
        decision = row.decision_json or {}
        return {
            "status": "OK",
            "symbol": row.symbol,
            "timestamp_utc": row.timestamp_utc,
            "decision_id": row.decision_id,
            "market_regime": evidence.get("market_regime") or "NOT_AVAILABLE",
            "selected_strategy": evidence.get("selected_strategy") or "NOT_AVAILABLE",
            "strategy_version": evidence.get("strategy_version") or "NOT_AVAILABLE",
            "strategy_fit_score": evidence.get("strategy_fit_score", "NOT_AVAILABLE"),
            "dominant_factor": evidence.get("dominant_factor") or "NOT_AVAILABLE",
            "supporting_factors": evidence.get("supporting_factors") or [],
            "contradicting_factors": evidence.get("contradicting_factors") or [],
            "action": decision.get("action") or "NOT_AVAILABLE",
            "raw_llm_confidence": decision.get("raw_llm_confidence", "NOT_AVAILABLE"),
            "evidence_adjusted_confidence": decision.get(
                "evidence_adjusted_confidence", "NOT_AVAILABLE"
            ),
            "reason_codes": decision.get("reason_codes") or [],
            "strategy_candidates": evidence.get("strategy_candidates") or [],
            "factor_snapshot_id": row.factor_snapshot_id or "NOT_AVAILABLE",
            "factor_set_version": row.factor_set_version or "NOT_AVAILABLE",
            "llm_invocation_id": evidence.get("llm_invocation_id") or "NOT_AVAILABLE",
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
        account = await state.portfolio.get_account(state.settings.effective_mode())
        positions = await state.portfolio.get_positions()
        equity = account.equity or Decimal("0")
        gross_notional = sum(
            abs(position.quantity * (position.avg_entry_price or Decimal("0")))
            for position in positions.values()
        )
        spot_leverage = (
            gross_notional / equity if equity > 0 and gross_notional > 0 else Decimal("0")
        )
        metrics: dict = {
            "current_drawdown": "NOT_AVAILABLE",
            "risk_multiplier": "NOT_AVAILABLE",
            "effective_leverage": str(spot_leverage),
            "margin_ratio": "NOT_AVAILABLE" if positions else "0",
            "flat": not positions,
        }
        # §21: risk panel must understand PAPER PERPETUAL state. When a
        # BTCUSDT_PERP LONG/SHORT exists, leverage/margin/liquidation come
        # from the futures projection + real reference mark price.
        try:
            if state.engine is not None and state.engine.perpetual_engine is not None:
                perp_engine = state.engine.perpetual_engine
                perp_state = await perp_engine.load_state()
                perp_position = perp_state.positions.get(
                    perp_engine.contract.symbol
                )
                if perp_position is not None and not perp_position.is_flat:
                    contract = perp_engine.contract
                    reference_symbol = reference_symbol_for(perp_position.symbol)
                    book = state.market_data.books.get(reference_symbol)
                    mark_price = book.mid_price() if book is not None else None
                    notional = (
                        abs(perp_position.quantity)
                        * perp_position.avg_entry_price
                        * contract.contract_size
                    )
                    metrics["flat"] = False
                    metrics["effective_leverage"] = str(
                        notional / perp_position.initial_margin
                        if perp_position.initial_margin
                        else "NOT_AVAILABLE"
                    )
                    metrics["margin_ratio"] = str(
                        perp_position.maintenance_margin
                        / perp_position.initial_margin
                        if perp_position.initial_margin
                        else "NOT_AVAILABLE"
                    )
                    metrics["liquidation_price"] = str(
                        perp_position.liquidation_price
                        if perp_position.liquidation_price is not None
                        else "NOT_AVAILABLE"
                    )
                    metrics["mark_price"] = (
                        str(mark_price) if mark_price is not None else "NOT_AVAILABLE"
                    )
                    if mark_price is not None and perp_position.liquidation_price:
                        distance = abs(mark_price - perp_position.liquidation_price)
                        metrics["liquidation_distance"] = str(
                            distance / mark_price if mark_price > 0 else "NOT_AVAILABLE"
                        )
                    else:
                        metrics["liquidation_distance"] = "NOT_AVAILABLE"
        except Exception:
            pass
        return {
            "trading_mode": state.settings.effective_mode().value,
            "live_trading_enabled": state.settings.live_trading_enabled,
            "kill_switch": state.risk.kill_switch.snapshot(),
            "risk_config": state.risk.config.model_dump(mode="json"),
            # Display metrics derived from canonical portfolio state. Metrics
            # the system does not track are reported as NOT_AVAILABLE, never
            # faked.
            "metrics": metrics,
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
        market_snapshot = await market()
        return {
            "market_data": {
                "provider": "OKX",
                "mode": "REAL" if state.settings.paper_mode == "PAPER_REAL_MARKET" else "SYNTHETIC",
                "status": market_snapshot.get("status", "UNAVAILABLE"),
            },
            "execution": {
                "provider": "LOCAL_PAPER",
                "environment": "LOCAL",
                "configured": True,
                "authenticated": False,
                "health": "CONNECTED" if adapter_connected else "DISCONNECTED",
                "status": "CONNECTED" if adapter_connected else "DISCONNECTED",
            },
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
        # §20: one read-only position truth. Spot positions + PAPER PERPETUAL
        # state are merged so the frontend can never show "空仓" while
        # BTCUSDT_PERP LONG/SHORT is actually open.
        positions = await state.portfolio.get_positions()
        payload = {symbol: pos.model_dump(mode="json") for symbol, pos in positions.items()}
        try:
            if state.engine is not None and state.engine.perpetual_engine is not None:
                engine = state.engine.perpetual_engine
                perp_state = await engine.load_state()
                for symbol, position in perp_state.positions.items():
                    if position.is_flat:
                        continue
                    book = state.market_data.books.get(
                        reference_symbol_for(symbol)
                    )
                    mark_price = (
                        book.mid_price() if book is not None else None
                    )
                    payload[symbol] = {
                        "symbol": symbol,
                        "base_asset": engine.contract.base,
                        "quote_asset": engine.contract.quote,
                        "quantity": str(position.quantity),
                        "avg_entry_price": str(position.avg_entry_price),
                        "cost_basis": str(position.initial_margin),
                        "realized_pnl": str(position.realized_pnl),
                        "updated_at": position.ts.isoformat(),
                        "market_type": "PERPETUAL",
                        "side": position.side.value,
                        "unrealized_pnl": str(position.unrealized_pnl),
                        "leverage": (
                            str(
                                abs(position.quantity)
                                * position.avg_entry_price
                                / position.initial_margin
                            )
                            if position.initial_margin
                            else "NOT_AVAILABLE"
                        ),
                        "initial_margin": str(position.initial_margin),
                        "liquidation_price": str(
                            position.liquidation_price
                            if position.liquidation_price is not None
                            else "NOT_AVAILABLE"
                        ),
                        "mark_price": (
                            str(mark_price)
                            if mark_price is not None
                            else "NOT_AVAILABLE"
                        ),
                    }
        except Exception:
            # Perpetual projection is read-only state; failure must never break
            # the spot positions endpoint.
            pass
        return payload

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
