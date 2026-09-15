"""Fast Profit Protection (Low-Risk V2 Phase 4J).

Deterministic risk-reducing authority available online and offline. It may
sell 1..100% of an existing leg only when ALL THREE conditions hold:

  1. the position is estimated NET profitable after all-in costs;
  2. profit expanded rapidly relative to ATR/volatility (normalized);
  3. material opposite/reversal evidence exists (CVD reversal, book
     deterioration, volume climax, price rejection, large opposite trade).

A lone large trade or a fast move is explicitly insufficient. The module only
reduces/closes an existing factual position; it can never OPEN/ADD/HEDGE/
REVERSE and it never creates new risk. After triggering, the caller must ask
the Core LLM for a fresh reassessment with the latest factual state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.factors.expert.context import AllInCostEstimate
from crypto_trader.market_data.state import MarketState


@dataclass(frozen=True, slots=True)
class FastProfitConfig:
    # Engineering defaults, configurable and Growth-validated later.
    expansion_atr_multiple: float = 1.5
    min_net_profit_pct: float = 0.20
    min_reversal_score: float = 0.8
    cvd_reversal_ratio: float = 0.15
    orderbook_against: float = 0.30
    rvol_climax: float = 2.0
    large_trade_notional_usd: Decimal = Decimal("100000")
    base_exit_pct: float = 25.0
    strong_exit_pct: float = 50.0
    severe_exit_pct: float = 100.0
    strong_score: float = 1.5
    severe_score: float = 2.2
    min_exit_notional_usd: Decimal = Decimal("100")


@dataclass(slots=True)
class FastProfitDecision:
    symbol: str
    trigger: bool
    side: str
    exit_pct: float
    exit_notional_usd: Decimal
    net_profit_pct: float
    expansion_ratio: float
    reversal_score: float
    reason_codes: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    blocking_reasons: list[str] = field(default_factory=list)
    authority: str = "FAST_PROFIT_PROTECTION"
    is_new_risk: bool = False
    requires_llm_reassessment: bool = True

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "trigger": self.trigger,
            "side": self.side,
            "exit_pct": self.exit_pct,
            "exit_notional_usd": str(self.exit_notional_usd),
            "net_profit_pct": self.net_profit_pct,
            "expansion_ratio": self.expansion_ratio,
            "reversal_score": self.reversal_score,
            "reason_codes": list(self.reason_codes),
            "evidence": dict(self.evidence),
            "blocking_reasons": list(self.blocking_reasons),
            "authority": self.authority,
            "is_new_risk": self.is_new_risk,
            "requires_llm_reassessment": self.requires_llm_reassessment,
        }


def _net_profit_pct(side: str, entry: Decimal, mark: Decimal, cost_pct: float) -> float:
    if entry <= 0 or mark <= 0:
        return -1.0
    if side.upper() in ("LONG", "BUY"):
        gross = float((mark - entry) / entry)
    else:
        gross = float((entry - mark) / entry)
    return (gross * 100.0) - cost_pct


def _reversal_evidence(
    side: str,
    state: MarketState | None,
    *,
    price_rejection: bool,
    rvol: float | None,
    config: FastProfitConfig,
) -> tuple[float, dict, list[str]]:
    score = 0.0
    evidence: dict = {}
    reasons: list[str] = []
    long_position = side.upper() in ("LONG", "BUY")
    if state is not None:
        total_flow = (state.taker_buy_volume or Decimal("0")) + (
            state.taker_sell_volume or Decimal("0")
        )
        cvd = state.cvd
        if cvd is not None and total_flow > 0:
            flow_against = (-cvd if long_position else cvd) / total_flow
            evidence["cvd_against_ratio"] = float(flow_against)
            if float(flow_against) >= config.cvd_reversal_ratio:
                score += 1.0
                reasons.append("CVD_REVERSAL")
        imbalance = float(state.imbalance_l5)
        book_against = -imbalance if long_position else imbalance
        evidence["orderbook_against"] = book_against
        if book_against >= config.orderbook_against:
            score += 0.7
            reasons.append("ORDERBOOK_DETERIORATION")
        largest = state.largest_trade_notional
        evidence["largest_trade_notional"] = float(largest or 0)
        if (
            largest is not None
            and largest >= config.large_trade_notional_usd
            and (cvd is not None and (cvd < 0 if long_position else cvd > 0))
        ):
            score += 0.5
            reasons.append("LARGE_OPPOSITE_TRADE")
    if rvol is not None:
        evidence["rvol"] = rvol
        if rvol >= config.rvol_climax:
            score += 0.5
            reasons.append("VOLUME_CLIMAX")
    if price_rejection:
        score += 0.8
        reasons.append("PRICE_REJECTION")
    return score, evidence, reasons


def evaluate_fast_profit(
    *,
    symbol: str,
    side: str,
    quantity: Decimal,
    entry_price: Decimal,
    mark_price: Decimal,
    atr_pct: float,
    state: MarketState | None = None,
    costs: AllInCostEstimate | None = None,
    price_rejection: bool = False,
    rvol: float | None = None,
    contract_size: Decimal = Decimal("1"),
    contract_multiplier: Decimal = Decimal("1"),
    config: FastProfitConfig | None = None,
) -> FastProfitDecision:
    """Evaluate Fast Profit Protection. Deterministic; online or offline."""
    cfg = config or FastProfitConfig()
    cost = costs or AllInCostEstimate()
    cost_pct = cost.total_cost_bps / 100.0  # bps -> percent
    net_profit_pct = _net_profit_pct(side, entry_price, mark_price, cost_pct)
    notional = abs(quantity) * mark_price * contract_size * contract_multiplier
    threshold_pct = max(
        cfg.min_net_profit_pct, cfg.expansion_atr_multiple * max(atr_pct, 0.0) * 100.0
    )
    expansion_ratio = (
        net_profit_pct / threshold_pct if threshold_pct > 0 else 0.0
    )
    reversal_score, evidence, reasons = _reversal_evidence(
        side, state, price_rejection=price_rejection, rvol=rvol, config=cfg
    )
    blocking: list[str] = []
    if side.upper() not in ("LONG", "BUY", "SHORT", "SELL"):
        blocking.append("INVALID_SIDE")
    if net_profit_pct <= 0:
        blocking.append("NOT_NET_PROFITABLE")
    elif expansion_ratio < 1.0:
        blocking.append("NO_RAPID_PROFIT_EXPANSION")
    if reversal_score < cfg.min_reversal_score:
        blocking.append("INSUFFICIENT_REVERSAL_EVIDENCE")

    exit_pct = 0.0
    if not blocking:
        if reversal_score >= cfg.severe_score or expansion_ratio >= 3.0:
            exit_pct = cfg.severe_exit_pct
        elif reversal_score >= cfg.strong_score:
            exit_pct = cfg.strong_exit_pct
        else:
            exit_pct = cfg.base_exit_pct
        exit_pct = max(1.0, min(100.0, exit_pct))
        exit_notional = notional * Decimal(str(exit_pct / 100.0))
        if exit_notional < cfg.min_exit_notional_usd:
            # Avoid an uneconomic fragment: use the full factual leg only when
            # that itself is economically meaningful; otherwise do nothing.
            if notional >= cfg.min_exit_notional_usd:
                exit_pct = 100.0
            else:
                exit_pct = 0.0
                blocking.append("EXIT_FRAGMENT_UNECONOMIC")
        reasons.append(f"EXIT_{exit_pct:g}PCT")

    trigger = bool(exit_pct > 0 and not blocking)
    exit_notional = notional * Decimal(str(exit_pct / 100.0)) if trigger else Decimal("0")
    return FastProfitDecision(
        symbol=symbol,
        trigger=trigger,
        side="LONG" if side.upper() in ("LONG", "BUY") else "SHORT",
        exit_pct=exit_pct if trigger else 0.0,
        exit_notional_usd=exit_notional,
        net_profit_pct=net_profit_pct,
        expansion_ratio=expansion_ratio,
        reversal_score=reversal_score,
        reason_codes=reasons if trigger else [],
        evidence=evidence,
        blocking_reasons=blocking,
    )


def exit_side_for_fast_profit(position_side: str) -> OrderSide:
    """Reduce/close side for the existing leg; never opens new risk."""
    return OrderSide.SELL if position_side.upper() in ("LONG", "BUY") else OrderSide.BUY
