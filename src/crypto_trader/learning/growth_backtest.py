"""Backtest -> canonical Growth episode adapter.

Backtest evidence reuses the one canonical Growth pipeline; it is only
namespaced by evidence_domain=BACKTEST and gated by mandatory provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from crypto_trader.governance.trade_episode import FactualTradeEpisode
from crypto_trader.learning.growth_domains import (
    EVIDENCE_DOMAIN_BACKTEST,
    validate_backtest_provenance,
)
from crypto_trader.learning.growth_knowledge import EpisodeBinding


@dataclass(frozen=True)
class BacktestTrade:
    episode_id: str
    symbol: str
    direction: str
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    leverage: Decimal
    fees: Decimal
    funding_pnl: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    holding_time_seconds: float
    entry_market_regime: str
    terminal_reason: str
    opened_at: datetime
    closed_at: datetime
    provenance: dict


class BacktestEpisodeAdapter:
    """Convert one backtest trade into the canonical closed-episode shape."""

    @staticmethod
    def evidence_identity(trade: BacktestTrade) -> str:
        provenance = trade.provenance or {}
        raw = "|".join(
            (
                str(provenance.get("backtest_run_id") or ""),
                str(provenance.get("dataset_id") or ""),
                str(provenance.get("dataset_hash") or ""),
                str(provenance.get("strategy_hash") or ""),
                str(provenance.get("parameter_set_hash") or ""),
                str(trade.episode_id),
            )
        )
        return f"bt_{sha256(raw.encode('utf-8')).hexdigest()[:32]}"

    def to_factual_episode(self, trade: BacktestTrade) -> FactualTradeEpisode:
        validate_backtest_provenance(trade.provenance)
        return FactualTradeEpisode(
            episode_id=trade.episode_id,
            trade_plan_id=f"bt-plan-{trade.episode_id}",
            symbol=trade.symbol,
            direction=trade.direction,
            entry_decision_id=f"bt-entry-{trade.episode_id}",
            exit_decision_id=f"bt-exit-{trade.episode_id}",
            position_decision_ids=[],
            risk_decision_ids=[],
            order_ids=[],
            fill_ids=[],
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            opened_quantity=trade.quantity,
            closed_quantity=trade.quantity,
            leverage=trade.leverage,
            fees=trade.fees,
            funding_pnl=trade.funding_pnl,
            gross_pnl=trade.gross_pnl,
            net_pnl=trade.net_pnl,
            holding_time_seconds=trade.holding_time_seconds,
            entry_market_regime=trade.entry_market_regime,
            terminal_reason=trade.terminal_reason,
            opened_at=trade.opened_at,
            closed_at=trade.closed_at,
        )

    def to_binding(
        self,
        trade: BacktestTrade,
        *,
        account_id: str = "default",
        currency: str = "USDT",
        canonical_regime: str,
    ) -> EpisodeBinding:
        validate_backtest_provenance(trade.provenance)
        return EpisodeBinding(
            account_id=account_id,
            mode=EVIDENCE_DOMAIN_BACKTEST,
            currency=currency,
            instrument_id=trade.symbol,
            source_revision=str(trade.provenance["backtest_run_id"]),
            terminal_reason=trade.terminal_reason,
            funding_provenance="PROVEN",
            proof_kind="BACKTEST",
            regime=canonical_regime,
            direction=trade.direction,
            evidence_domain=EVIDENCE_DOMAIN_BACKTEST,
            backtest_provenance=dict(trade.provenance),
            backtest_evidence_identity=self.evidence_identity(trade),
        )
