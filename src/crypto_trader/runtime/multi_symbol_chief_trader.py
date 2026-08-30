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
        market_observer=None,
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
        # Phase C/D + P3 correction: hierarchical all-market observer whose
        # non-core attention is owned by the Market Observer AI (ADVISORY
        # evidence only; no volume/Top-K authority). Candidates never gate
        # entries; they only widen the rotation and enrich the decision
        # context with factual Layer-1 summaries.
        self.market_observer = market_observer
        self._dynamic_symbols: tuple[str, ...] = ()
        self._last_observer_refresh_mono: float = 0.0
        self._observer_failures = 0

    @property
    def rotation_symbols(self) -> tuple[str, ...]:
        """Core symbols ALWAYS retained + bounded dynamic observer candidates."""
        merged = list(self.symbols)
        for symbol in self._dynamic_symbols:
            if symbol not in merged:
                merged.append(symbol)
        return tuple(merged[:40])

    @property
    def dynamic_symbols(self) -> tuple[str, ...]:
        return self._dynamic_symbols

    @property
    def symbol(self) -> str:
        """Return the next symbol for TradingEngine._strategy_context()."""
        rotation = self.rotation_symbols
        current = rotation[self._symbol_cursor % len(rotation)]
        self._symbol_cursor = (self._symbol_cursor + 1) % len(rotation)
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
            _s0 = time.monotonic()
            score = await self._score_opportunity(ctx)
            self._record_opportunity(score)
            if self.tool_journal is not None:
                try:
                    self.tool_journal.defer(
                        "opportunity_scan",
                        symbol=ctx.symbol,
                        latency_ms=int((time.monotonic() - _s0) * 1000),
                        status="OK" if score.eligible else "NOT_AVAILABLE",
                        detail=f"score={score.score:.3f}",
                    )
                except Exception:
                    pass

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
        chief_ctx = await super()._build_context(ctx)
        await self._refresh_market_observer(chief_ctx)
        return chief_ctx

    async def _refresh_market_observer(self, chief_ctx) -> None:
        """Phase C/D advisory injection. NEVER raises, NEVER gates: observer
        failure simply leaves the evidence key absent (fail-open, logged).

        P1 CS-20260830-034530-P3-AI-ATTENTION: dynamic rotation slots are
        chosen by the Market Observer AI (attention), not by volume rank.
        """
        if self.market_observer is None:
            return
        try:
            held: list[str] = []
            portfolio_positions = (chief_ctx.portfolio_state or {}).get("positions") or {}
            for symbol, position in portfolio_positions.items():
                try:
                    if isinstance(position, dict):
                        quantity = position.get("quantity")
                    else:
                        quantity = getattr(position, "quantity", 0)
                    if float(quantity or 0) != 0:
                        held.append(symbol)
                except (TypeError, ValueError):
                    continue
            target = 5
            if self.policy_manager is not None:
                snap = self._policy_snapshot()
                if snap is not None:
                    try:
                        target = int(snap.get("deep_analysis_candidate_limit"))
                    except (TypeError, ValueError):
                        target = 5
            _o0 = time.monotonic()
            candidate = await self.market_observer.select_candidates(
                target=target,
                held_canonical_symbols=tuple(held),
                core_canonical_symbols=self.symbols,
            )
            self.market_observer.update_ws_candidates(candidate)
            self._dynamic_symbols = self.market_observer.canonical_symbols_for(candidate)
            attention = getattr(candidate, "attention", None)
            if attention is not None:
                self._defer_attention_row(
                    str(getattr(chief_ctx, "symbol", "") or ""), attention
                )
            summary = self.market_observer.observe(candidate)
            if summary.get("available"):
                chief_ctx.strategy_evidence["market_observer"] = summary
                if self.tool_journal is not None:
                    self.tool_journal.defer(
                        "market_observer_evidence",
                        symbol=chief_ctx.symbol,
                        latency_ms=int((time.monotonic() - _o0) * 1000),
                        status="OK",
                        detail=(
                            "candidates="
                            f"{len((summary.get('candidates') or {}).get('facts') or {})}"
                            f" source={summary.get('source')}"
                        ),
                    )
        except Exception as exc:
            self._observer_failures += 1
            logger.warning(
                "MARKET_OBSERVER_EVIDENCE_UNAVAILABLE failures=%d error=%s",
                self._observer_failures,
                type(exc).__name__,
            )

    def _defer_attention_row(self, symbol: str, attention) -> None:
        """Journal the Market Observer AI attention invocation (fail-safe).

        The attention decision itself is durably persisted by the observer's
        lineage sink (market_attention_decisions); this row ties it into the
        decision-pipeline tool trace.
        """
        if self.tool_journal is None:
            return
        mode = str(getattr(attention, "mode", "") or "")
        if mode == "AI_SELECTED":
            status = "OK"
        elif mode in ("AI_UNAVAILABLE",):
            status = "ERROR"
        else:
            status = "NOT_AVAILABLE"
        try:
            self.tool_journal.defer(
                "market_observer_ai",
                symbol=symbol,
                latency_ms=int(getattr(attention, "latency_ms", 0) or 0),
                status=status,
                detail=(
                    f"mode={mode} selected={len(getattr(attention, 'selected_inst_ids', ()) or ())}"
                    f" roster={getattr(attention, 'roster_size', 0)}"
                    f" uid={getattr(attention, 'attention_uid', '')}"
                ),
            )
        except Exception:
            pass
