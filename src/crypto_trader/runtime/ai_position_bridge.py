"""AI position re-evaluation bridge.

Calls AITradingBrain for each active position on the existing supervisor loop.
This module NEVER executes orders; it only produces decisions and maps them to
existing SignalIntent-compatible shapes via runtime_adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.ai_brain.decision.decision_engine import AITradingBrain
from crypto_trader.ai_brain.runtime_adapter import map_trading_intent
from crypto_trader.runtime.execution_symbols import reference_symbol_for


@dataclass
class AIPositionEvaluation:
    symbol: str
    action: str
    confidence: float
    reason: str
    thesis_status: str
    executable: bool
    side: str
    quantity: float
    reduce_only: bool
    market_type: str = "SPOT"
    position_side: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "confidence": self.confidence,
            "reason": self.reason,
            "thesis_status": self.thesis_status,
            "executable": self.executable,
            "side": self.side,
            "quantity": self.quantity,
            "reduce_only": self.reduce_only,
            "market_type": self.market_type,
            "position_side": self.position_side,
            "timestamp": self.timestamp,
        }


class AIPositionRuntimeBridge:
    def __init__(
        self,
        brain: AITradingBrain | None = None,
        cooldown_seconds: float = 5.0,
        perpetual_engine=None,
        time_stop_seconds: float | None = None,
        position_opened_at_provider=None,
    ) -> None:
        self.brain = brain or AITradingBrain()
        self.cooldown_seconds = cooldown_seconds
        self.perpetual_engine = perpetual_engine
        self.last_evaluation: dict[str, str] = {}
        self.last_decision: dict[str, str] = {}
        self.decision_history: list[dict] = []
        self.thesis_overrides: dict[str, str] = {}
        self.requested_change_overrides: dict[str, float] = {}
        self.hard_risk_overrides: dict[str, bool] = {}
        # §17 PAPER time stop: exploration entries must COMPLETE to produce
        # outcome data. When set (PAPER exploration only), a position held
        # longer than time_stop_seconds is force-closed reduce-only. Position
        # age is tracked in-memory from the first tick a position is seen open
        # (slight undercount; documented for PAPER v1).
        self.time_stop_seconds = time_stop_seconds
        # Optional async (symbol, side) -> datetime | None: the REAL open
        # time of the current position episode. Hydrating the time-stop age
        # from it keeps the clock honest across process restarts (a restart
        # must never silently grant positions a fresh holding window).
        self.position_opened_at_provider = position_opened_at_provider
        self._first_seen_open: dict[str, datetime] = {}
        self._missing_since: dict[str, datetime] = {}
        # Reduce-only EXITs already applied but not yet observed flat: a
        # later evaluation round (tick path AND supervisor 5s callback can
        # interleave) must not fire a duplicate EXIT for the same symbol.
        self._exit_in_flight: set[str] = set()

    def evaluate(
        self,
        *,
        symbol: str,
        active_position: dict,
        market_state: str = "UNKNOWN",
        factor_intelligence: dict | None = None,
        now: datetime | None = None,
    ) -> AIPositionEvaluation:
        now = now or datetime.now(UTC)
        if self._on_cooldown(symbol, now):
            return AIPositionEvaluation(
                symbol, "COOLDOWN", 0.0, "cooldown", "", False, "", 0.0, False
            )
        intent = self.brain.analyze(
            symbol=symbol,
            market_state=market_state,
            factor_intelligence=factor_intelligence,
            active_position=active_position,
        )
        side = str(active_position.get("side", "LONG")).upper()
        market_type = str(active_position.get("market_type", "SPOT")).upper()
        quantity = float(active_position.get("quantity", 0.0))
        requested_change = float(active_position.get("requested_change", 0.0))
        mapping = map_trading_intent(
            intent_action=intent.action,
            position_side=side,
            position_quantity=quantity,
            requested_change=requested_change,
        )
        evaluation = AIPositionEvaluation(
            symbol=symbol,
            action=intent.action,
            confidence=intent.confidence,
            reason=intent.thesis or "position analysis",
            thesis_status=str(active_position.get("thesis_status", "")),
            executable=mapping.executable,
            side=mapping.side,
            quantity=mapping.quantity,
            reduce_only=mapping.reduce_only,
            market_type=market_type,
            position_side=side,
        )
        self.last_decision[symbol] = evaluation.action
        self.last_evaluation[symbol] = now.isoformat()
        self.decision_history.append(evaluation.to_dict())
        return evaluation

    def _on_cooldown(self, symbol: str, now: datetime) -> bool:
        last = self.last_evaluation.get(symbol)
        if last is None:
            return False
        try:
            last_ts = datetime.fromisoformat(last)
            return (now - last_ts).total_seconds() < self.cooldown_seconds
        except Exception:
            return False

    async def evaluate_active_positions(self, engine, portfolio) -> list[AIPositionEvaluation]:
        # Snapshot both position sources up front, before any order submission,
        # so DB reads do not race the async fill-settlement loop.
        candidates: list[tuple] = []
        spot_positions = await portfolio.get_positions()
        for symbol, position in spot_positions.items():
            raw_quantity = float(position.quantity or 0)
            if raw_quantity == 0:
                continue
            candidates.append(
                (
                    symbol,
                    "SPOT",
                    "LONG" if raw_quantity > 0 else "SHORT",
                    abs(raw_quantity),
                    float(position.avg_entry_price or 0),
                    float(position.realized_pnl or 0),
                )
            )

        if self.perpetual_engine is not None:
            try:
                state = await self.perpetual_engine.load_state()
                for symbol, mpos in state.positions.items():
                    if mpos.is_flat:
                        continue
                    candidates.append(
                        (
                            symbol,
                            "PERPETUAL",
                            mpos.side.value,
                            abs(float(mpos.quantity or 0)),
                            float(mpos.avg_entry_price or 0),
                            float(mpos.realized_pnl or 0),
                        )
                    )
            except Exception:
                pass

        evaluations: list[AIPositionEvaluation] = []
        seen_symbols: set[str] = set()
        for symbol, market_type, side, abs_quantity, entry_price, realized_pnl in candidates:
            seen_symbols.add(symbol)
            if symbol in self._exit_in_flight:
                continue
            await self._evaluate_one(
                engine,
                evaluations,
                symbol=symbol,
                market_type=market_type,
                side=side,
                abs_quantity=abs_quantity,
                entry_price=entry_price,
                realized_pnl=realized_pnl,
            )
        # Positions no longer open: forget their age tracking. A transient
        # empty/partial position read must NOT reset the time-stop clock for
        # still-open positions, so a symbol is only forgotten after it has
        # been continuously absent for a full grace window.
        now_utc = datetime.now(UTC)
        grace = max(60.0, float(self.cooldown_seconds or 0.0))
        for symbol in set(self._first_seen_open) - seen_symbols:
            missing_since = self._missing_since.setdefault(symbol, now_utc)
            if (now_utc - missing_since).total_seconds() >= grace:
                self._first_seen_open.pop(symbol, None)
                self._missing_since.pop(symbol, None)
        for symbol in seen_symbols:
            self._missing_since.pop(symbol, None)
        for symbol in set(self._exit_in_flight) - seen_symbols:
            self._exit_in_flight.discard(symbol)
        return evaluations

    async def _evaluate_one(
        self,
        engine,
        evaluations: list[AIPositionEvaluation],
        *,
        symbol: str,
        market_type: str,
        side: str,
        abs_quantity: float,
        entry_price: float,
        realized_pnl: float,
    ) -> None:
        current_price = entry_price
        book = getattr(engine, "market_data", None)
        if book is not None:
            # §13: perpetual positions are marked against the real reference
            # market book (BTCUSDT), never against a BTCUSDT_PERP book.
            reference_symbol = reference_symbol_for(symbol)
            orderbook = book.books.get(reference_symbol)
            if orderbook is not None:
                mid = orderbook.mid_price()
                if mid is not None:
                    current_price = float(mid)
        if current_price > 0 and entry_price > 0:
            if side == "LONG":
                unrealized_pnl = (current_price - entry_price) * abs_quantity
            else:
                unrealized_pnl = (entry_price - current_price) * abs_quantity
        else:
            unrealized_pnl = 0.0
        active_position = {
            "quantity": abs_quantity,
            "side": side,
            "market_type": market_type,
            "entry_price": entry_price,
            "current_price": current_price,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": realized_pnl,
            "age_seconds": 0.0,
            "thesis_status": self.thesis_overrides.get(symbol, "THESIS_INTACT"),
            "thesis": "position management",
            "hard_risk_exit": self.hard_risk_overrides.get(symbol, False),
            "requested_change": self.requested_change_overrides.get(symbol, 0.0),
        }
        # §17 PAPER exploration time stop (checked before the AI brain so a
        # stale position exits even if the brain is unavailable).
        if self.time_stop_seconds is not None:
            first_seen = self._first_seen_open.get(symbol)
            if first_seen is None:
                first_seen = None
                if self.position_opened_at_provider is not None:
                    try:
                        first_seen = await self.position_opened_at_provider(symbol, side)
                    except Exception:
                        first_seen = None
                first_seen = first_seen or datetime.now(UTC)
                self._first_seen_open[symbol] = first_seen
            age_seconds = (datetime.now(UTC) - first_seen).total_seconds()
            if age_seconds >= self.time_stop_seconds:
                close_side = "SELL" if side == "LONG" else "BUY"
                evaluation = AIPositionEvaluation(
                    symbol=symbol,
                    action="EXIT",
                    confidence=1.0,
                    reason=(
                        f"EXPLORATION_TIME_STOP held {age_seconds:.0f}s >= "
                        f"{self.time_stop_seconds:.0f}s"
                    ),
                    thesis_status="THESIS_EXPIRED",
                    executable=True,
                    side=close_side,
                    quantity=abs_quantity,
                    reduce_only=True,
                    market_type=market_type,
                    position_side=side,
                )
                self.last_decision[symbol] = "EXIT"
                self.last_evaluation[symbol] = datetime.now(UTC).isoformat()
                self._exit_in_flight.add(symbol)
                self.decision_history.append(
                    {"symbol": symbol, "action": "EXIT", "reason": evaluation.reason,
                     "time_stop": True, "at": self.last_evaluation[symbol]}
                )
                evaluations.append(evaluation)
                if evaluation.executable:
                    await self._apply_to_engine(engine, symbol, evaluation)
                return
        evaluation = self.evaluate(symbol=symbol, active_position=active_position)
        evaluations.append(evaluation)
        if evaluation.executable and evaluation.action in ("ADD", "REDUCE", "EXIT"):
            await self._apply_to_engine(engine, symbol, evaluation)

    async def _apply_to_engine(self, engine, symbol: str, evaluation: AIPositionEvaluation) -> None:
        from datetime import UTC, datetime

        from crypto_trader.domain.enums import MarketType, OrderSide, OrderType, PositionSide
        from crypto_trader.domain.models import SignalIntent

        side = OrderSide.BUY if evaluation.side == "BUY" else OrderSide.SELL
        market_type = (
            MarketType(evaluation.market_type) if evaluation.market_type else MarketType.SPOT
        )
        position_side = (
            PositionSide(evaluation.position_side)
            if evaluation.position_side
            else PositionSide.FLAT
        )
        signal_id = f"ai_{symbol}_{int(datetime.now(UTC).timestamp() * 1000)}"
        signal = SignalIntent(
            signal_id=signal_id,
            strategy_id="ai_brain",
            symbol=symbol,
            side=side,
            quantity=str(evaluation.quantity),
            order_type=OrderType.MARKET,
            reason=evaluation.reason,
            market_type=market_type,
            position_side=position_side,
            reduce_only=evaluation.reduce_only,
        )
        await engine.process_signal(signal)
