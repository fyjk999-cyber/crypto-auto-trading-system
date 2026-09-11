"""FastAPI control plane. Routes are thin: validation/auth/service/response only."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from starlette.websockets import WebSocketDisconnect

from crypto_trader.api.deps import AppState
from crypto_trader.config import get_settings
from crypto_trader.domain.enums import OrderSide
from crypto_trader.domain.models import SignalIntent
from crypto_trader.domain.money import D
from crypto_trader.exchange.okx import OKXAdapter, OKXDiagnosticError
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.exposure.service import ExposureService
from crypto_trader.factors.service import FactorService
from crypto_trader.governance.factual_learning import FactualEpisodeLearning
from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.governance.scheduler import DailyReviewScheduler
from crypto_trader.intelligence.feedback.interface import ResearchFeedbackInterface
from crypto_trader.llm_chief.decision_store import LLMDecisionStore
from crypto_trader.okx_vault.client import BrokerClient
from crypto_trader.perpetual.domain import PerpetualContract, PositionSide
from crypto_trader.perpetual.engine import PerpetualPaperEngine
from crypto_trader.persistence.models import (
    LLMDecisionORM,
    RiskDecisionORM,
    TradeEpisodeORM,
    TradePlanORM,
)
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


def _num_or_none(value) -> str | None:
    return str(value) if value is not None else None


def serialize_order(order) -> dict:
    return order.model_dump(mode="json")


def serialize_position(position, *, price: Decimal | None = None) -> dict:
    """Serialize a position with the same canonical exposure used by Risk."""

    payload = position.model_dump(mode="json")
    exposure = ExposureService.for_position(position, price=price)
    payload["gross_notional"] = str(exposure.gross_notional)
    payload["signed_notional"] = str(exposure.signed_notional)
    payload["mark_price"] = str(price) if price is not None else None
    if (
        price is not None
        and position.avg_entry_price is not None
        and position.instrument_type.upper()
        not in {"INVERSE", "INVERSE_PERP", "INVERSE_FUTURES"}
    ):
        payload["unrealized_pnl"] = str(
            (price - position.avg_entry_price)
            * position.quantity
            * position.contract_size
            * position.contract_multiplier
        )
    else:
        payload["unrealized_pnl"] = None
    return payload


def serialize_valuation(batch) -> dict | None:
    """Return the one canonical valuation batch (or explicit UNAVAILABLE)."""
    if batch is None:
        return {
            "valuation_id": None,
            "quality": "UNAVAILABLE",
            "raw_mtm_equity": None,
            "available_margin": None,
            "adjusted_equity": None,
            "peak_adjusted_equity": None,
            "drawdown_amount": None,
            "drawdown_ratio": None,
            "market_as_of": None,
            "ledger_watermark": None,
            "position_snapshot_ref": None,
            "missing_marks": [],
            "stale_marks": [],
            "components": [],
            "solvency": None,
            "reason_codes": ["NO_VALUATION_BATCH"],
        }
    return batch.to_evidence()


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

    @app.get("/opportunity/board")
    async def opportunity_board():
        """Evidence-only full-market opportunity snapshot (MASTER DIRECTIVE §29).

        Read-only: proves candidates, factor evidence presence, and whether
        DeepSeek traded with vs without factor evidence. No authority surface.
        """
        board = state.opportunity_board
        if board is None:
            return {"enabled": False}
        return board.snapshot()

    @app.get("/opportunity/candidates")
    async def opportunity_candidates():
        """Current factor-nominated candidates (evidence only, never signals)."""
        board = state.opportunity_board
        if board is None:
            return {"enabled": False, "candidates": []}
        snap = board.snapshot()
        return {
            "enabled": True,
            "candidate_count": snap["candidate_count"],
            "candidates": snap["candidates"],
            "updated_at": snap["updated_at"],
        }

    @app.get("/opportunity/stats")
    async def opportunity_stats():
        """Counters proving factor-optional behavior (§29)."""
        board = state.opportunity_board
        if board is None:
            return {"enabled": False}
        snap = board.snapshot()
        return {
            "enabled": True,
            "universe_size": snap["universe_size"],
            "eligible_count": snap["eligible_count"],
            "market_sets": snap.get("market_sets"),
            "executable_scope": "USDT_LINEAR_SWAP_ONLY",
            "unsupported_products": {
                "SPOT": "NOT_EXECUTABLE",
                "FUTURES": "NOT_EXECUTABLE",
                "INVERSE_SWAP": "NOT_EXECUTABLE",
            },
            "candidate_count": snap["candidate_count"],
            "scan_stats": snap["scan_stats"],
            "stats": snap["stats"],
            "recent_decisions": snap["recent_decisions"],
            "rotation_symbols": snap.get("rotation_symbols", []),
        }

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

    @app.get("/llm/decisions")
    async def llm_decisions(limit: int = 100):
        rows = await LLMDecisionStore(state.database.session_factory).list_recent(limit)
        return {
            "decisions": [
                {
                    **row.__dict__,
                    "position_state": row.position_state.value,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ],
            "count": len(rows),
        }

    @app.get("/llm/decisions/{decision_id}")
    async def llm_decision_detail(decision_id: str):
        async with state.database.session_factory() as session:
            row = await session.get(LLMDecisionORM, decision_id)
            if row is None:
                raise HTTPException(status_code=404, detail="decision not found")
            return {
                "decision_id": row.decision_id,
                "run_id": row.run_id,
                "symbol": row.symbol,
                "position_state": row.position_state,
                "action": row.action,
                "model_provider": row.model_provider,
                "model": row.model,
                "model_version": row.model_version,
                "prompt_version": row.prompt_version,
                "market_regime": row.market_regime,
                "thesis": row.thesis,
                "reason_codes": row.reason_codes_json or [],
                "supporting_evidence": row.supporting_evidence_json or [],
                "contradicting_evidence": row.contradicting_evidence_json or [],
                "tool_refs": row.tool_refs_json or [],
                "memory_refs": row.memory_refs_json or [],
                "research_refs": row.research_refs_json or [],
                "episode_refs": row.episode_refs_json or [],
                "requested_exposure": _num_or_none(row.requested_exposure),
                "requested_quantity": _num_or_none(row.requested_quantity),
                "requested_leverage": _num_or_none(row.requested_leverage),
                "parent_decision_id": row.parent_decision_id,
                "trade_plan_id": row.trade_plan_id,
                "position_quantity_before": _num_or_none(
                    row.position_quantity_before
                ),
                "entry_price": _num_or_none(row.entry_price),
                "mark_price": _num_or_none(row.mark_price),
                "unrealized_pnl": _num_or_none(row.unrealized_pnl),
                "time_in_trade_seconds": row.time_in_trade_seconds,
                "original_trade_plan_id": row.original_trade_plan_id,
                "original_entry_decision_id": row.original_entry_decision_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }

    @app.get("/trade-plans")
    async def trade_plans(limit: int = 100):
        async with state.database.session_factory() as session:
            rows = (
                await session.execute(
                    select(TradePlanORM)
                    .order_by(TradePlanORM.created_at.desc())
                    .limit(max(1, min(limit, 500)))
                )
            ).scalars().all()
            return {
                "trade_plans": [
                    {
                        "trade_plan_id": r.trade_plan_id,
                        "decision_id": r.decision_id,
                        "symbol": r.symbol,
                        "direction": r.direction,
                        "state": r.state.value if hasattr(r.state, "value") else str(r.state),
                        "thesis": r.thesis,
                        "requested_quantity": _num_or_none(r.requested_quantity),
                        "requested_leverage": _num_or_none(r.requested_leverage),
                        "requested_exposure": _num_or_none(r.requested_exposure),
                        "entry_conditions": r.entry_conditions_json or [],
                        "invalidation_conditions": r.invalidation_conditions_json or [],
                        "reduce_conditions": r.reduce_conditions_json or [],
                        "exit_conditions": r.exit_conditions_json or [],
                        "expected_holding_period": r.expected_holding_period,
                        "max_holding_time_seconds": r.max_holding_time_seconds,
                        "signal_id": r.signal_id,
                        "risk_decision_id": r.risk_decision_id,
                        "order_id": r.order_id,
                        "latest_position_decision_id": r.latest_position_decision_id,
                        "exit_decision_id": r.exit_decision_id,
                        "opened_at": r.opened_at.isoformat() if r.opened_at else None,
                        "closed_at": r.closed_at.isoformat() if r.closed_at else None,
                        "terminal_reason": r.terminal_reason,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in rows
                ],
                "count": len(rows),
            }

    @app.get("/trade-episodes")
    async def trade_episodes(limit: int = 100):
        async with state.database.session_factory() as session:
            rows = (
                await session.execute(
                    select(TradeEpisodeORM)
                    .order_by(TradeEpisodeORM.closed_at.desc())
                    .limit(max(1, min(limit, 500)))
                )
            ).scalars().all()
            return {
                "trade_episodes": [
                    {
                        "episode_id": r.episode_id,
                        "trade_plan_id": r.trade_plan_id,
                        "symbol": r.symbol,
                        "direction": r.direction,
                        "entry_decision_id": r.entry_decision_id,
                        "exit_decision_id": r.exit_decision_id,
                        "position_decision_ids": r.position_decision_ids_json or [],
                        "risk_decision_ids": r.risk_decision_ids_json or [],
                        "order_ids": r.order_ids_json or [],
                        "fill_ids": r.fill_ids_json or [],
                        "entry_price": str(r.entry_price),
                        "exit_price": str(r.exit_price),
                        "opened_quantity": str(r.opened_quantity),
                        "closed_quantity": str(r.closed_quantity),
                        "leverage": str(r.leverage),
                        "fees": str(r.fees),
                        "funding_pnl": str(r.funding_pnl),
                        "gross_pnl": str(r.gross_pnl),
                        "net_pnl": str(r.net_pnl),
                        "holding_time_seconds": r.holding_time_seconds,
                        "entry_market_regime": r.entry_market_regime,
                        "terminal_reason": r.terminal_reason,
                        "factual": bool(r.factual),
                        "review_status": r.review_status,
                        "opened_at": r.opened_at.isoformat() if r.opened_at else None,
                        "closed_at": r.closed_at.isoformat() if r.closed_at else None,
                    }
                    for r in rows
                ],
                "count": len(rows),
            }

    @app.get("/ready")
    async def ready():
        """Strict PAPER runtime readiness for acceptance and automation.

        A process being alive is not enough. Readiness requires the canonical
        PAPER mode, single-writer execution lease, an untripped kill switch,
        a reachable configured DeepSeek provider, and factual OKX public
        market data for the baseline instrument. No synthetic fallback is
        accepted here.
        """

        reasons: list[str] = []
        database_ok = True
        try:
            async with state.database.session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            database_ok = False
            reasons.append("DATABASE_UNAVAILABLE")

        runtime = state.engine.runtime_snapshot() if state.engine is not None else None
        execution_lease = (runtime or {}).get("execution_lease") or {}
        kill_switch = (runtime or {}).get("kill_switch") or {}
        mode_ok = (
            state.settings.effective_mode().value == "PAPER"
            and state.settings.live_trading_enabled is False
            and state.settings.paper_mode == "PAPER_REAL_MARKET"
        )
        if not mode_ok:
            reasons.append("PAPER_REAL_MARKET_REQUIRED")
        runtime_ok = (
            runtime is not None
            and runtime.get("state") == "RUNNING"
            and execution_lease.get("held") is True
            and execution_lease.get("single_writer") is True
            and kill_switch.get("enabled") is False
        )
        if not runtime_ok:
            reasons.append("RUNTIME_NOT_EXECUTION_READY")

        llm = state.llm_runtime.snapshot()
        llm_ok = (
            llm.get("provider") == "deepseek"
            and llm.get("configured") is True
            and llm.get("reachable") is True
            and bool(llm.get("model"))
        )
        if not llm_ok:
            reasons.append("DEEPSEEK_NOT_READY")

        market = {
            "provider": "OKX_PUBLIC",
            "data_source": "REAL",
            "symbol": "BTCUSDT",
            "healthy": False,
        }
        market_ok = False
        if state.engine is not None and state.settings.paper_mode == "PAPER_REAL_MARKET":
            get_market_state = getattr(state.engine.adapter, "get_market_state", None)
            if callable(get_market_state):
                try:
                    snapshot = await get_market_state("BTCUSDT")
                    health = getattr(getattr(snapshot, "health", None), "value", None)
                    provider = getattr(snapshot, "provider", None)
                    data_source = getattr(snapshot, "data_source", None)
                    best_bid = getattr(snapshot, "best_bid", Decimal("0"))
                    best_ask = getattr(snapshot, "best_ask", Decimal("0"))
                    market_ok = (
                        health == "HEALTHY"
                        and provider == "OKX_PUBLIC"
                        and data_source == "REAL"
                        and best_bid > 0
                        and best_ask > 0
                    )
                    market = {
                        "provider": provider,
                        "data_source": data_source,
                        "symbol": getattr(snapshot, "symbol", "BTCUSDT"),
                        "healthy": market_ok,
                    }
                except Exception:
                    market_ok = False
        if not market_ok:
            reasons.append("OKX_PUBLIC_MARKET_NOT_READY")

        is_ready = database_ok and mode_ok and runtime_ok and llm_ok and market_ok
        payload = {
            "ready": is_ready,
            "mode": state.settings.effective_mode().value,
            "paper_mode": state.settings.paper_mode,
            "live_trading_enabled": state.settings.live_trading_enabled,
            "runtime": runtime,
            "llm": llm,
            "market": market,
            "reasons": reasons,
        }
        return JSONResponse(payload, status_code=200 if is_ready else 503)

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

    async def _position_mark_prices(positions: dict) -> dict[str, Decimal]:
        adapter = getattr(state.engine, "adapter", None) if state.engine else None
        get_market_state = getattr(adapter, "get_market_state", None)
        prices: dict[str, Decimal] = {}
        if get_market_state is None:
            return prices
        for symbol in positions:
            try:
                snapshot = await get_market_state(symbol)
            except Exception:
                continue
            price = snapshot.mark_price or snapshot.last_price
            if price is not None and D(price) > 0:
                prices[symbol] = D(price)
        return prices

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
        if state.engine is not None and state.engine.enforce_llm_entry_authority:
            raise HTTPException(status_code=403, detail="NEW_DIRECTION_REQUIRES_LIVE_LLM")
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
        if state.engine is not None and state.engine.enforce_llm_entry_authority:
            raise HTTPException(status_code=403, detail="POSITION_ACTION_REQUIRES_LIVE_LLM")
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
    async def market(symbol: str = "BTCUSDT"):
        symbol = symbol.upper()
        try:
            SymbolMapper().to_okx(symbol)
        except ValueError:
            return {
                "symbol": symbol,
                "provider": "OKX_PUBLIC",
                "source": "OKX_PUBLIC",
                "status": "INVALID_SYMBOL",
                "data_source": "REAL",
            }
        adapter = getattr(state.engine, "adapter", None) if state.engine else None
        get_market_state = getattr(adapter, "get_market_state", None)
        if get_market_state is not None:
            try:
                ms = await get_market_state(symbol)
                return ms.model_dump(mode="json")
            except Exception as exc:
                return {
                    "symbol": symbol,
                    "provider": "OKX_PUBLIC",
                    "source": "OKX_PUBLIC",
                    "status": "UNAVAILABLE",
                    "data_source": "REAL",
                    "last_error": type(exc).__name__,
                }
        if state.settings.paper_mode == "PAPER_SYNTHETIC":
            return {
                "provider": "SYNTHETIC",
                "source": "SYNTHETIC",
                "status": "SYNTHETIC",
                "data_source": "SYNTHETIC",
                "symbol": symbol,
            }
        return {
            "provider": "OKX_PUBLIC",
            "source": "OKX_PUBLIC",
            "status": "UNAVAILABLE",
            "data_source": "REAL",
            "symbol": symbol,
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
    async def market_sources(symbol: str = "BTCUSDT"):
        symbol = symbol.upper()
        try:
            SymbolMapper().to_okx(symbol)
        except ValueError:
            return {
                "symbol": symbol,
                "provider": "OKX_PUBLIC",
                "source": "OKX_PUBLIC",
                "status": "INVALID_SYMBOL",
                "data_source": "REAL",
            }
        adapter = getattr(state.engine, "adapter", None) if state.engine else None
        get_market_state = getattr(adapter, "get_market_state", None)
        if get_market_state is not None:
            try:
                ms = await get_market_state(symbol)
                return {k: v.model_dump(mode="json") for k, v in ms.sources.items()}
            except Exception as exc:
                return {
                    "symbol": symbol,
                    "provider": "OKX_PUBLIC",
                    "source": "OKX_PUBLIC",
                    "status": "UNAVAILABLE",
                    "data_source": "REAL",
                    "last_error": type(exc).__name__,
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
        rows = await LLMDecisionStore(state.database.session_factory).list_recent(limit)
        return {
            "signals": [
                {
                    "decision_id": row.decision_id,
                    "symbol": row.symbol,
                    "side": row.action,
                    "decision": row.action,
                    "position_state": row.position_state.value,
                    "reasons": row.reason_codes,
                    "regime": row.market_regime,
                    "thesis": row.thesis,
                    "trade_plan_id": row.trade_plan_id,
                    "provider": row.model_provider,
                    "model": row.model,
                    "created_at": row.created_at.isoformat(),
                    "authority": "CHIEF_TRADER_LLM",
                    "executable": False,
                }
                for row in rows
            ],
            "count": len(rows),
            "quant_direct_trade_authority": 0,
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
        batch = await state.portfolio.latest_valuation_batch(
            account_id=account.account_id, currency="USDT"
        )
        async with state.database.session_factory() as session:
            last = (
                await session.execute(
                    select(RiskDecisionORM)
                    .order_by(RiskDecisionORM.timestamp.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        checks = (last.checks_json or {}) if last is not None else {}
        last_risk = None
        if last is not None:
            last_risk = {
                "risk_decision_id": last.risk_decision_id,
                "symbol": last.symbol,
                "decision": last.decision,
                "reason": last.reason,
                "timestamp": last.timestamp.isoformat() if last.timestamp else None,
                "requested_quantity": checks.get("original_quantity"),
                "approved_quantity": checks.get("approved_quantity"),
                "requested_leverage": checks.get("requested_leverage"),
                "approved_leverage": checks.get("approved_leverage"),
                "daily_pnl": checks.get("daily_pnl"),
                "daily_pnl_source": checks.get("daily_pnl_source"),
                "funding_status": checks.get("funding_status"),
                "valuation_id": checks.get("valuation_id"),
                "valuation_quality": checks.get("valuation_quality"),
                "available_margin": checks.get("available_margin"),
                "pnl_provenance": checks.get("pnl_provenance") or {},
            }
        return {
            "trading_mode": state.settings.effective_mode().value,
            "live_trading_enabled": state.settings.live_trading_enabled,
            "kill_switch": state.risk.kill_switch.snapshot(),
            "risk_config": state.risk.config.model_dump(mode="json"),
            "valuation": serialize_valuation(batch),
            "last_risk_decision": last_risk,
        }

    @app.get("/margin")
    async def margin():
        account = await state.portfolio.get_account(state.settings.effective_mode())
        positions = await state.portfolio.get_positions()
        prices = await _position_mark_prices(positions)
        serialized = {
            symbol: serialize_position(pos, price=prices.get(symbol))
            for symbol, pos in positions.items()
        }
        exposure = ExposureService.for_portfolio(positions, prices=prices)
        batch = await state.portfolio.latest_valuation_batch(
            account_id=account.account_id, currency="USDT"
        )
        return {
            "equity": str(account.equity),
            "valuation": serialize_valuation(batch),
            "balances": {k: v.model_dump(mode="json") for k, v in account.balances.items()},
            "positions": serialized,
            "gross_exposure": str(exposure.gross_notional),
            "net_exposure": str(exposure.signed_notional),
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
                "provider": "LOCAL_PAPER_SIMULATOR",
                "mode": state.settings.effective_mode().value,
                "live_trading_enabled": state.settings.live_trading_enabled,
                "status": "HEALTHY" if adapter_connected else "DISCONNECTED",
            },
            "okx_demo_credentials": {
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
        prices = await _position_mark_prices(positions)
        return {
            symbol: serialize_position(pos, price=prices.get(symbol))
            for symbol, pos in positions.items()
        }

    @app.get("/account")
    async def account():
        account = await state.portfolio.get_account(state.settings.effective_mode())
        batch = await state.portfolio.latest_valuation_batch(
            account_id=account.account_id, currency="USDT"
        )
        payload = account.model_dump(mode="json")
        payload["valuation"] = serialize_valuation(batch)
        return payload

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
