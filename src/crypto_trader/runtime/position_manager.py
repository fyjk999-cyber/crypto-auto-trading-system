"""Shadow Position Manager (STRATEGY DIRECTIVE §15-§24, §76-§79).

Periodically re-evaluates OPEN positions against their entry thesis with a
bounded LLM review, producing HOLD / EXIT / REDUCE recommendations.

SHADOW MODE (this phase): recommendations are RECORDED ONLY — the manager
never submits orders, never mutates positions, and never bypasses Risk or
Execution. It exists to accumulate honest counterfactual evidence
(AI-exit-vs-TIME_STOP comparison) before any promotion (§78).

Authority model (§16/§17):
  - The manager owns NOTHING in shadow mode. In a future ACTIVE mode its
    recommendation flows AI -> RiskEngine -> ExecutionAuthority.
  - HOLD is a first-class legal outcome (§24); the manager must never be
    forced to produce an exit.
Resilience (§84):
  - LLM calls use a short timeout and limited retries; any failure degrades
    to SKIP for that review cycle and never blocks the engine hot path.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from crypto_trader.runtime.trade_thesis import TradeThesis

REVIEW_TIMEOUT_SECONDS = 15.0
REVIEW_RETRIES = 0  # shadow: prefer skip over latency; §84


@dataclass(slots=True)
class ShadowReview:
    symbol: str
    direction: str
    episode_key: str
    review_timestamp: str
    holding_seconds: float
    entry_price: str | None
    current_price: str | None
    unrealized_pnl: str | None
    recommended_action: str  # HOLD | EXIT | REDUCE | SKIP
    reason_summary: str
    llm_invocation_id: str | None = None
    thesis_decision_id: str | None = None
    executed: bool = False  # always False in shadow mode (§76)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "episode_key": self.episode_key,
            "review_timestamp": self.review_timestamp,
            "holding_seconds": self.holding_seconds,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "unrealized_pnl": self.unrealized_pnl,
            "recommended_action": self.recommended_action,
            "reason_summary": self.reason_summary,
            "llm_invocation_id": self.llm_invocation_id,
            "thesis_decision_id": self.thesis_decision_id,
            "executed": self.executed,
        }


class ShadowPositionManager:
    """Bounded, non-blocking shadow review loop (§15/§18)."""

    def __init__(
        self,
        provider,
        *,
        review_interval_seconds: float = 600.0,
        max_reviews_per_cycle: int = 8,
        journal=None,
    ) -> None:
        self.provider = provider
        self.review_interval_seconds = float(review_interval_seconds)
        self.max_reviews_per_cycle = int(max_reviews_per_cycle)
        self.journal = journal
        self._last_review_mono: dict[str, float] = {}
        self.stats = {"reviews": 0, "hold": 0, "exit": 0, "reduce": 0, "skips": 0, "errors": 0}

    # ------------------------------------------------------------------ gate
    def due_symbols(self, open_positions: dict, *, now_mono: float | None = None) -> list[str]:
        """Symbols whose bounded review interval has elapsed (§18)."""
        now_mono = time.monotonic() if now_mono is None else now_mono
        due: list[str] = []
        for symbol in list(open_positions)[: 4 * self.max_reviews_per_cycle]:
            last = self._last_review_mono.get(symbol)
            if last is None or (now_mono - last) >= self.review_interval_seconds:
                due.append(symbol)
        return due[: self.max_reviews_per_cycle]

    # ---------------------------------------------------------------- review
    async def review_symbol(
        self,
        symbol: str,
        *,
        position: dict,
        thesis: TradeThesis | None,
        current_price,
        episode_key: str = "",
    ) -> ShadowReview:
        now = datetime.now(timezone.utc)
        entry_price = position.get("entry_price") or position.get("avg_price")
        quantity = position.get("quantity") or 0
        direction = str(
            position.get("direction")
            or position.get("side")
            or (thesis.direction if thesis else "")
            or "UNKNOWN"
        ).upper()
        holding_seconds = 0.0
        opened_at = position.get("opened_at") or position.get("entry_time")
        if opened_at is not None:
            try:
                holding_seconds = max(0.0, now.timestamp() - float(opened_at))
            except (TypeError, ValueError):
                holding_seconds = 0.0
        unrealized = None
        try:
            if current_price is not None and entry_price is not None:
                diff = float(current_price) - float(entry_price)
                if direction == "SHORT":
                    diff = -diff
                unrealized = diff * float(quantity)
        except (TypeError, ValueError):
            unrealized = None

        prompt = self._build_prompt(
            symbol=symbol,
            direction=direction,
            thesis=thesis,
            entry_price=entry_price,
            current_price=current_price,
            holding_seconds=holding_seconds,
            unrealized=unrealized,
        )
        recommended, reason, inv_id = await self._ask_ai(prompt)

        review = ShadowReview(
            symbol=symbol,
            direction=direction,
            episode_key=episode_key,
            review_timestamp=now.isoformat(),
            holding_seconds=holding_seconds,
            entry_price=str(entry_price) if entry_price is not None else None,
            current_price=str(current_price) if current_price is not None else None,
            unrealized_pnl=unrealized,
            recommended_action=recommended,
            reason_summary=reason,
            llm_invocation_id=inv_id,
            thesis_decision_id=thesis.decision_id if thesis else None,
            executed=False,
        )
        self._last_review_mono[symbol] = time.monotonic()
        self.stats["reviews"] += 1
        self.stats[{"HOLD": "hold", "EXIT": "exit", "REDUCE": "reduce"}.get(recommended, "skips")] += 1
        if self.journal is not None:
            try:
                self.journal.defer(
                    tool_name="position_review",
                    status="OK" if recommended != "SKIP" else "NOT_AVAILABLE",
                    payload={
                        "symbol": symbol,
                        "action": recommended,
                        "shadow": True,
                        "reason": reason[:200],
                    },
                )
            except Exception:
                self.stats["errors"] += 1
        return review

    # -------------------------------------------------------------- internals
    def _build_prompt(
        self,
        *,
        symbol: str,
        direction: str,
        thesis: TradeThesis | None,
        entry_price,
        current_price,
        holding_seconds: float,
        unrealized,
    ) -> str:
        thesis_json = json.dumps(thesis.as_dict(), ensure_ascii=False) if thesis else "NOT_AVAILABLE"
        return (
            "You are the Position Manager reviewing ONE open PAPER position.\n"
            "Decide only: HOLD, EXIT, or REDUCE. HOLD is normal and expected; "
            "EXIT only when the entry thesis is invalidated or targets met. "
            "There is no penalty for HOLD.\n\n"
            f"SYMBOL: {symbol}\nDIRECTION: {direction}\n"
            f"ENTRY_PRICE: {entry_price}\nCURRENT_PRICE: {current_price}\n"
            f"HOLDING_SECONDS: {holding_seconds:.0f}\nUNREALIZED_PNL: {unrealized}\n"
            f"ENTRY_THESIS (canonical, may be NOT_AVAILABLE): {thesis_json}\n\n"
            'Reply with JSON only: {"action": "HOLD|EXIT|REDUCE", "reason": "<=200 chars", '
            '"llm_invocation_id": null}'
        )

    async def _ask_ai(self, prompt: str) -> tuple[str, str, str | None]:
        try:
            resp = await self.provider.complete_json(
                prompt=prompt,
                temperature=0.1,
                timeout_seconds=REVIEW_TIMEOUT_SECONDS,
                retries=REVIEW_RETRIES,
            )
            text = getattr(resp, "text", "") or ""
            data = json.loads(text) if isinstance(text, str) and text.strip() else {}
        except Exception:
            self.stats["errors"] += 1
            return "SKIP", "position review unavailable (LLM error/timeout)", None
        action = str(data.get("action") or "").upper()
        if action not in ("HOLD", "EXIT", "REDUCE"):
            self.stats["skips"] += 1
            return "SKIP", f"unparseable review response: {text[:120]}", None
        reason = str(data.get("reason") or "")[:200]
        return action, reason, data.get("llm_invocation_id")
