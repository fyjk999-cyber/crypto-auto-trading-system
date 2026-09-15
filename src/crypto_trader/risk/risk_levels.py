"""Risk L1/L2 protection layer (Low-Risk V2 Phase 4H).

Risk is a 24/7 deterministic protection layer, not a pre-trade strategy gate.
It does not choose size, leverage or whether to enter: those belong to the
Core LLM and are contract-validated by execution.

Levels (all thresholds are configurable engineering candidates, not frozen
strategy law):

  L1 -> warning + Core LLM reassessment request. If the Core LLM chain
        (DeepSeek + retry, GLM + retry) cannot be reached, the caller must
        escalate L1 to an immediate forced close (no five-minute wait).
  L2 -> forced hard exit, deterministic, no LLM required.

A Risk Episode belongs to the factual position/leg. ADD does not reset its
history, and an L2 latch is never cleared by a favourable price move.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from crypto_trader.domain.identifiers import new_id


class RiskLevel(StrEnum):
    NONE = "NONE"
    L1 = "L1"
    L2 = "L2"


@dataclass(frozen=True, slots=True)
class RiskLevelConfig:
    """Engineering candidates pending Growth validation (SPEC §4H)."""

    l1_position_loss_pct: float = 2.5
    l2_position_loss_pct: float = 5.0
    l1_account_drawdown_pct: float = 5.0
    l2_account_drawdown_pct: float = 10.0
    label: str = "ENGINEERING_CANDIDATE_NOT_FROZEN_STRATEGY_LAW"


@dataclass(slots=True)
class PositionRiskEpisode:
    leg_id: str
    symbol: str
    side: str  # LONG | SHORT
    entry_price: Decimal
    episode_id: str = field(default_factory=lambda: new_id("riskip"))
    l1_hits: int = 0
    l2_hits: int = 0
    add_count: int = 0
    latched_level: RiskLevel = RiskLevel.NONE
    forced_close: bool = False
    last_evaluated_at: datetime | None = None
    history: list[dict] = field(default_factory=list)

    def record_add(self, *, reason: str = "LLM_AUTHORIZED_ADD") -> None:
        """An ADD extends the episode; it never resets L1/L2 history."""
        self.add_count += 1
        self.history.append(
            {
                "event": "ADD",
                "at": datetime.now(UTC).isoformat(),
                "reason": reason,
                "l1_hits": self.l1_hits,
                "l2_hits": self.l2_hits,
                "latch": self.latched_level.value,
            }
        )

    def as_dict(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "leg_id": self.leg_id,
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": str(self.entry_price),
            "l1_hits": self.l1_hits,
            "l2_hits": self.l2_hits,
            "add_count": self.add_count,
            "latched_level": self.latched_level.value,
            "forced_close": self.forced_close,
            "label": "POSITION_RISK_EPISODE",
        }


@dataclass(slots=True)
class RiskLevelDecision:
    level: RiskLevel
    loss_pct: float
    requires_llm_reassessment: bool
    force_close: bool
    reason_codes: list[str] = field(default_factory=list)
    episode: dict = field(default_factory=dict)
    config_label: str = "ENGINEERING_CANDIDATE_NOT_FROZEN_STRATEGY_LAW"

    def as_dict(self) -> dict:
        return {
            "level": self.level.value,
            "loss_pct": self.loss_pct,
            "requires_llm_reassessment": self.requires_llm_reassessment,
            "force_close": self.force_close,
            "reason_codes": list(self.reason_codes),
            "episode": dict(self.episode),
            "config_label": self.config_label,
        }


def _adverse_move_pct(side: str, entry: Decimal, mark: Decimal) -> float:
    if entry <= 0 or mark <= 0:
        return 0.0
    if side.upper() in ("LONG", "BUY"):
        return float((mark - entry) / entry) * 100.0
    return float((entry - mark) / entry) * 100.0


class PositionRiskMonitor:
    """Deterministic L1/L2 evaluation. Never sizes or shrinks a trade."""

    def __init__(self, config: RiskLevelConfig | None = None) -> None:
        self.config = config or RiskLevelConfig()

    def evaluate(
        self,
        episode: PositionRiskEpisode,
        *,
        mark_price: Decimal,
        account_drawdown_pct: float = 0.0,
        now: datetime | None = None,
    ) -> RiskLevelDecision:
        moment = now or datetime.now(UTC)
        move_pct = _adverse_move_pct(episode.side, episode.entry_price, mark_price)
        loss_pct = max(0.0, -move_pct)  # 0 when profitable
        cfg = self.config
        reasons: list[str] = []
        level = RiskLevel.NONE
        if (
            loss_pct >= cfg.l2_position_loss_pct
            or account_drawdown_pct >= cfg.l2_account_drawdown_pct
        ):
            level = RiskLevel.L2
            reasons.append("L2_HARD_EXIT")
            if loss_pct >= cfg.l2_position_loss_pct:
                reasons.append("POSITION_LOSS_LIMIT")
            if account_drawdown_pct >= cfg.l2_account_drawdown_pct:
                reasons.append("ACCOUNT_DRAWDOWN_LIMIT")
        elif (
            loss_pct >= cfg.l1_position_loss_pct
            or account_drawdown_pct >= cfg.l1_account_drawdown_pct
        ):
            level = RiskLevel.L1
            reasons.append("L1_WARNING_LLM_REASSESSMENT")
            if loss_pct >= cfg.l1_position_loss_pct:
                reasons.append("POSITION_LOSS_WARNING")
            if account_drawdown_pct >= cfg.l1_account_drawdown_pct:
                reasons.append("ACCOUNT_DRAWDOWN_WARNING")

        rank = {RiskLevel.NONE: 0, RiskLevel.L1: 1, RiskLevel.L2: 2}
        if rank[level] > rank[episode.latched_level]:
            episode.latched_level = level
        effective_level = episode.latched_level
        if effective_level == RiskLevel.L2 and episode.forced_close:
            level = RiskLevel.L2
        elif rank[episode.latched_level] > rank[level]:
            # Latch is sticky: a recovered price does not clear an episode hit.
            level = episode.latched_level
            reasons.append("RISK_EPISODE_LATCHED")

        if level == RiskLevel.L2:
            episode.l2_hits += 1
            episode.forced_close = True
            reasons.append("FORCED_CLOSE_REQUIRED")
        elif level == RiskLevel.L1:
            episode.l1_hits += 1
        episode.last_evaluated_at = moment
        episode.history.append(
            {
                "event": "EVALUATE",
                "at": moment.isoformat(),
                "level": level.value,
                "loss_pct": loss_pct,
                "account_drawdown_pct": account_drawdown_pct,
                "reasons": list(reasons),
            }
        )
        return RiskLevelDecision(
            level=level,
            loss_pct=loss_pct,
            requires_llm_reassessment=level == RiskLevel.L1,
            force_close=level == RiskLevel.L2,
            reason_codes=reasons,
            episode=episode.as_dict(),
        )

    def escalate_l1_to_force_close(
        self,
        episode: PositionRiskEpisode,
        decision: RiskLevelDecision,
        *,
        reason: str = "LLM_PROVIDERS_UNAVAILABLE",
    ) -> RiskLevelDecision:
        """L1 + failed Core LLM chain -> immediate forced close (no 5m wait)."""
        if decision.level != RiskLevel.L1:
            return decision
        episode.forced_close = True
        episode.latched_level = RiskLevel.L2
        episode.l2_hits += 1
        episode.history.append(
            {
                "event": "L1_ESCALATED",
                "at": datetime.now(UTC).isoformat(),
                "reason": reason,
            }
        )
        return RiskLevelDecision(
            level=RiskLevel.L2,
            loss_pct=decision.loss_pct,
            requires_llm_reassessment=False,
            force_close=True,
            reason_codes=[*decision.reason_codes, reason, "L1_ESCALATED_TO_FORCED_CLOSE"],
            episode=episode.as_dict(),
        )
