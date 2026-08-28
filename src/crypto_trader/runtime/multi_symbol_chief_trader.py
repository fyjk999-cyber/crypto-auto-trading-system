"""Round-robin multi-symbol wrapper for the canonical Chief Trader.

TradingEngine intentionally remains unchanged. It asks the first strategy for
its current ``symbol`` when building StrategyContext; this adapter rotates that
symbol across the configured universe one coin per engine tick.

Architecture doctrine: AI-FIRST, QUANT-AS-EVIDENCE.
The cheap opportunity scanner is advisory only. It may summarize/rank market
conditions for observability, but it must never block the Chief Trader from
seeing a symbol. LLM decision throttling remains independent per symbol.
"""

from __future__ import annotations

import logging
import time

from crypto_trader.domain.models import SignalIntent
from crypto_trader.exchange.symbol_mapper import SymbolMapper
from crypto_trader.runtime.ai_first_chief_trader import AIFirstChiefTraderStrategyAdapter
from crypto_trader.runtime.opportunity_scanner import CheapOpportunityScanner, OpportunityScore
from crypto_trader.strategy.base import StrategyContext

logger = logging.getLogger("crypto_trader.multi_symbol_chief")


class MultiSymbolChiefTraderStrategyAdapter(AIFirstChiefTraderStrategyAdapter):
    version = "2.3.0"

    def __init__(
        self,
        *,
        symbols: tuple[str, ...] | list[str],
        opportunity_scanner: CheapOpportunityScanner | None = None,
        opportunity_scanner_enabled: bool = True,
        opportunity_top_k: int = 5,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        mapper = SymbolMapper()
        normalized = tuple(mapper.to_canonical(symbol) for symbol in symbols)
        if not normalized:
            raise ValueError("multi-symbol Chief Trader requires at least one symbol")
        if len(normalized) != len(set(normalized)):
            raise ValueError("multi-symbol Chief Trader symbols must be unique")
        self.symbols = normalized
        self._symbol_cursor = 0
        self.last_scan_symbol = normalized[0]
        self._last_decision_completed_by_symbol: dict[str, float] = {}
        self.opportunity_scanner_enabled = bool(opportunity_scanner_enabled)
        self.opportunity_scanner = opportunity_scanner or CheapOpportunityScanner()
        # Retained as an observability/UI preference only; it is NOT an entry gate.
        self.opportunity_top_k = max(1, min(int(opportunity_top_k), len(normalized)))
        self._opportunity_scores: dict[str, OpportunityScore] = {}
        self._seen_in_round: set[str] = set()
        self._opportunity_ranking: list[OpportunityScore] = []
        self._ranking_generation = 0

    @property
    def symbol(self) -> str:
        """Return the next symbol for TradingEngine._strategy_context()."""
        current = self.symbols[self._symbol_cursor]
        self._symbol_cursor = (self._symbol_cursor + 1) % len(self.symbols)
        self.last_scan_symbol = current
        return current

    @property
    def opportunity_ranking(self) -> list[dict]:
        return [item.to_dict() for item in self._opportunity_ranking]

    @property
    def eligible_symbols(self) -> tuple[str, ...]:
        """Compatibility view of the advisory Top-K ranking.

        This property no longer controls whether a symbol may reach the LLM.
        """
        return tuple(item.symbol for item in self._opportunity_ranking[: self.opportunity_top_k])

    async def on_market_data(self, ctx: StrategyContext) -> list[SignalIntent]:
        # Provider/data-route health remains a real safety prerequisite.
        if self.provider is None or not self.provider.healthy():
            return []
        if not getattr(self.provider, "route_ready", lambda: True)():
            return []

        # Quant/opportunity analysis is evidence and observability only. A low
        # score, non-Top-K rank, or incomplete ranking must never veto AI.
        if self.opportunity_scanner_enabled:
            score = await self._score_opportunity(ctx)
            self._record_opportunity(score)

        now = time.monotonic()
        last = self._last_decision_completed_by_symbol.get(ctx.symbol)
        if last is not None and now - last < self.min_decision_interval_seconds:
            return []
        try:
            return await self._decide(ctx)
        finally:
            self._last_decision_completed_by_symbol[ctx.symbol] = time.monotonic()

    async def _score_opportunity(self, ctx: StrategyContext) -> OpportunityScore:
        if self.decision_context_provider is None:
            return OpportunityScore(
                symbol=ctx.symbol,
                score=0.0,
                eligible=False,
                direction="NEUTRAL",
                spread_bps=0.0,
                components={},
                reason="DECISION_CONTEXT_UNAVAILABLE",
            )
        get_candles = getattr(self.decision_context_provider, "get_candles", None)
        if get_candles is None:
            return OpportunityScore(
                symbol=ctx.symbol,
                score=0.0,
                eligible=False,
                direction="NEUTRAL",
                spread_bps=0.0,
                components={},
                reason="CANDLE_ACCESS_UNAVAILABLE",
            )
        try:
            candles = await get_candles(ctx.symbol)
            return self.opportunity_scanner.score(ctx, candles)
        except Exception as exc:
            logger.warning(
                "OPPORTUNITY_SCAN_FAILED symbol=%s error=%s",
                ctx.symbol,
                type(exc).__name__,
            )
            return OpportunityScore(
                symbol=ctx.symbol,
                score=0.0,
                eligible=False,
                direction="NEUTRAL",
                spread_bps=0.0,
                components={},
                reason=f"SCAN_FAILED:{type(exc).__name__}",
            )

    def _record_opportunity(self, score: OpportunityScore) -> None:
        self._opportunity_scores[score.symbol] = score
        self._seen_in_round.add(score.symbol)
        if len(self._seen_in_round) < len(self.symbols):
            return

        # Keep every observed symbol in the ranking, including low-score and
        # ineligible entries. The ranking is informational only.
        ranked = sorted(
            self._opportunity_scores.values(),
            key=lambda item: (-item.score, item.symbol),
        )
        self._opportunity_ranking = ranked
        self._ranking_generation += 1
        self._seen_in_round.clear()
        logger.info(
            "OPPORTUNITY_RANKING_UPDATED generation=%s advisory_top=%s",
            self._ranking_generation,
            ",".join(item.symbol for item in ranked[: self.opportunity_top_k]) or "NONE",
        )

    async def _build_context(self, ctx: StrategyContext):
        # The base Chief Trader owns all decision/risk semantics. We only point
        # its real-data context provider at the coin currently being scanned.
        if self.decision_context_provider is not None:
            set_symbol = getattr(self.decision_context_provider, "set_symbol", None)
            if set_symbol is not None:
                set_symbol(ctx.symbol)
        return await super()._build_context(ctx)
