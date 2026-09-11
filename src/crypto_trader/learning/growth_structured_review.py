"""Built-in LLM structured-review runner (I07 operational enablement).

This composes the existing in-system components only:

* ``StructuredReviewService`` — the DeepSeek/structured-review provider path;
* ``GrowthKnowledgePublisher`` — evidence-graded lessons/patterns;
* ``DailyCardLearner`` + ``AdaptiveCardStore`` — pattern→card learning.

The runner never authors review content itself.  It builds factual
``EpisodeReviewInput`` objects from canonical closed episodes, lets the
in-system provider produce the structured review, persists every attempt and
publishes only provider-validated knowledge.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from crypto_trader.learning.growth_attribution import DailyCardLearner
from crypto_trader.learning.growth_contracts import EpisodeReviewInput, ToolEvidenceInput
from crypto_trader.learning.growth_experience import AdaptiveCardStore
from crypto_trader.learning.growth_knowledge import EpisodeBinding, GrowthKnowledgePublisher
from crypto_trader.learning.growth_models import GrowthPatternORM
from crypto_trader.learning.growth_review import (
    REVIEW_PROFILE_VERSION,
    STATUS_SUCCEEDED,
    StructuredReviewService,
)
from crypto_trader.learning.growth_v2_contracts import ContextSignature, TriggerSignature
from crypto_trader.persistence.models import (
    LLMDecisionORM,
    RiskDecisionORM,
    TradePlanORM,
)

Fence = Callable[[], Awaitable[bool]]

_TERMINAL_PROVIDER_ERRORS = (
    "NO_API_KEY",
    "AUTH",
    "401",
    "402",
    "403",
    "BALANCE",
    "INSUFFICIENT",
)


class StructuredReviewRunner:
    def __init__(
        self,
        session_factory,
        provider,
        *,
        publisher: GrowthKnowledgePublisher | None = None,
        owner: str = "structured-review",
        lease_seconds: int = 3600,
        profile_version: str = REVIEW_PROFILE_VERSION,
        timeout_seconds: float = 90.0,
        max_tokens: int = 2000,
        retries: int = 1,
        thinking: bool = True,
        bootstrap_cards: bool = True,
        max_episodes_per_run: int | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.publisher = publisher or GrowthKnowledgePublisher(session_factory)
        self.owner = owner
        self.lease_seconds = max(60, lease_seconds)
        self.service = StructuredReviewService(
            provider,
            session_factory,
            profile_version=profile_version,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            retries=retries,
            thinking=thinking,
        )
        self.bootstrap_cards = bootstrap_cards
        self.max_episodes_per_run = max_episodes_per_run

    # ------------------------------------------------------------------
    async def _entry_decision(self, decision_id: str | None) -> LLMDecisionORM | None:
        if not decision_id:
            return None
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(LLMDecisionORM).where(
                        LLMDecisionORM.decision_id == decision_id
                    )
                )
            ).scalar_one_or_none()

    async def _build_input(
        self, episode, *, account_id: str, mode: str
    ) -> EpisodeReviewInput:
        entry = await self._entry_decision(episode.entry_decision_id)
        missing: list[str] = []
        if episode.exit_decision_id is None:
            missing.append("EXIT_DECISION_MISSING")
        if not episode.order_ids:
            missing.append("ORDER_LINEAGE_MISSING")
        if not episode.fill_ids:
            missing.append("FILL_LINEAGE_MISSING")
        thesis = (entry.thesis if entry is not None else "") or ""
        if not thesis.strip():
            missing.append("ENTRY_THESIS_MISSING")

        tool_refs: list[str] = []
        triggered: list[dict[str, Any]] = []
        if entry is not None:
            tool_refs = [str(ref) for ref in (entry.tool_refs_json or [])][:32]
            triggered = [
                item
                for item in (entry.triggered_factors_json or [])
                if isinstance(item, dict)
            ][:32]

        trade_plan_payload: dict[str, Any] = {}
        async with self.session_factory() as session:
            plan = (
                await session.execute(
                    select(TradePlanORM).where(
                        TradePlanORM.trade_plan_id == episode.trade_plan_id
                    )
                )
            ).scalar_one_or_none()
            if plan is not None:
                trade_plan_payload = {
                    "trade_plan_id": plan.trade_plan_id,
                    "state": plan.state,
                    "thesis": (plan.thesis or "")[:1000],
                    "requested_quantity": str(plan.requested_quantity),
                    "requested_leverage": (
                        str(plan.requested_leverage)
                        if plan.requested_leverage is not None
                        else None
                    ),
                    "requested_exposure": (
                        str(plan.requested_exposure)
                        if plan.requested_exposure is not None
                        else None
                    ),
                    "terminal_reason": plan.terminal_reason,
                    "exit_decision_id": plan.exit_decision_id,
                }
            risk_adjustments: list[dict[str, Any]] = []
            risk_ids = list(episode.risk_decision_ids or [])
            if risk_ids:
                rows = (
                    await session.execute(
                        select(RiskDecisionORM).where(
                            RiskDecisionORM.risk_decision_id.in_(risk_ids)
                        )
                    )
                ).scalars().all()
                risk_adjustments = [
                    {
                        "risk_decision_id": row.risk_decision_id,
                        "decision": row.decision,
                        "reason": row.reason,
                    }
                    for row in rows
                ]

        selected_tools = []
        if tool_refs:
            selected_tools.append(
                ToolEvidenceInput(
                    tool_name="entry_decision_tool_refs",
                    source_refs=tool_refs,
                    finding={
                        "decision_id": episode.entry_decision_id,
                        "action": entry.action if entry is not None else None,
                        "market_regime": (
                            entry.market_regime if entry is not None else None
                        ),
                    },
                    data_quality="FACTUAL_DECISION_TRACE",
                    timestamp=entry.created_at if entry is not None else None,
                )
            )

        return EpisodeReviewInput(
            episode_id=episode.episode_id,
            account_id=account_id,
            mode=mode,
            symbol=episode.symbol,
            direction=episode.direction,
            currency="USDT",
            entry_decision_id=episode.entry_decision_id,
            exit_decision_id=episode.exit_decision_id,
            order_refs=list(episode.order_ids or []),
            fill_refs=list(episode.fill_ids or []),
            entry_price=episode.entry_price,
            exit_price=episode.exit_price,
            quantity=episode.closed_quantity,
            leverage=episode.leverage,
            fees=episode.fees,
            funding_pnl=episode.funding_pnl,
            # TradeEpisodeStore only materializes an episode after the
            # canonical funding proof; this is asserted in the fact store.
            funding_provenance="PROVEN",
            gross_pnl=episode.gross_pnl,
            net_pnl=episode.net_pnl,
            opened_at=episode.opened_at,
            closed_at=episode.closed_at,
            entry_market_regime=(episode.entry_market_regime or "UNKNOWN")[:64],
            terminal_reason=(episode.terminal_reason or "UNKNOWN")[:255],
            thesis=thesis[:2000],
            selected_tools=selected_tools,
            trade_plan=trade_plan_payload,
            risk_adjustments=risk_adjustments,
            position_actions=[],
            market_changes=triggered,
            missing_evidence=missing,
        )

    @staticmethod
    def _binding(episode, *, account_id: str, mode: str) -> EpisodeBinding:
        return EpisodeBinding(
            account_id=account_id,
            mode=mode,
            currency="USDT",
            instrument_id=episode.symbol,
            source_revision=f"factual-episode:{episode.episode_id}",
            terminal_reason=episode.terminal_reason or "UNKNOWN",
            funding_provenance="PROVEN",
            proof_kind="FACTUAL_EPISODE",
            regime=episode.entry_market_regime,
            direction=episode.direction,
        )

    async def _bootstrap_cards(self, attempts: list[Any]) -> dict[str, Any]:
        """Let the system turn published patterns into candidate cards."""
        if not self.bootstrap_cards or not attempts:
            return {"enabled": False, "applied": 0}
        learner = DailyCardLearner(self.session_factory)
        store = AdaptiveCardStore(self.session_factory)
        async with self.session_factory() as session:
            patterns = (
                await session.execute(
                    select(GrowthPatternORM)
                    .where(GrowthPatternORM.status.in_(("VALIDATED", "CONTESTED")))
                    .order_by(GrowthPatternORM.known_at.desc())
                    .limit(50)
                )
            ).scalars().all()
        applied = 0
        candidate_rules: list[str] = []
        for pattern in patterns:
            context = ContextSignature.from_market_state(
                {
                    "symbol": pattern.symbol or "UNKNOWN",
                    "instrument_class": None,
                    "regime": pattern.regime,
                    "direction": pattern.direction,
                },
                as_of=datetime.now(UTC),
                symbol=pattern.symbol or "UNKNOWN",
            )
            trigger = TriggerSignature.from_factor_states([], as_of=datetime.now(UTC))
            try:
                proposal = await learner.propose_from_pattern(
                    pattern=pattern,
                    reviews=attempts,
                    trigger=trigger,
                    context=context,
                    now=datetime.now(UTC),
                )
                result = await store.apply(proposal, now=datetime.now(UTC))
            except Exception:
                continue
            applied += 1
            candidate_rules.append(result.rule_id)
        return {"enabled": True, "applied": applied, "rule_ids": candidate_rules}

    # ------------------------------------------------------------------
    async def run_day(
        self,
        episodes: list[Any],
        *,
        review_date: str,
        fence: Fence,
        owner: str | None = None,
        lease_seconds: int | None = None,
        account_id: str = "default",
        mode: str = "PAPER",
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "status": "NO_EPISODES",
            "review_date": review_date,
            "reviewed_episode_ids": [],
            "attempts_total": 0,
            "attempts_succeeded": 0,
            "attempts_failed": 0,
            "usage_known": 0,
            "usage_unknown": 0,
            "stop_on_provider_error": False,
        }
        if self.max_episodes_per_run is not None:
            episodes = list(episodes)[: max(1, self.max_episodes_per_run)]
        if not episodes:
            return summary

        attempts: list[Any] = []
        bindings: dict[str, EpisodeBinding] = {}
        terminal_error: str | None = None
        input_failed_ids: list[str] = []
        last_input_error: str | None = None
        for episode in episodes:
            if not await fence():
                summary.update(status="CLAIM_LOST")
                return summary
            try:
                review_input = await self._build_input(
                    episode, account_id=account_id, mode=mode
                )
            except Exception as exc:
                # One malformed legacy episode must not block the others; the
                # episode stays PENDING and is retried after the input
                # boundary is fixed.
                summary["attempts_failed"] += 1
                input_failed_ids.append(getattr(episode, "episode_id", "UNKNOWN"))
                last_input_error = type(exc).__name__
                continue
            try:
                attempt = await self.service.review(
                    review_input,
                    review_date=review_date,
                    allowed_refs=review_input.derived_refs(),
                    owner=owner or self.owner,
                    claim_checker=fence,
                )
            except Exception as exc:
                attempt = type(
                    "FailedAttempt",
                    (),
                    {
                        "status": "FAILED",
                        "error_type": type(exc).__name__,
                        "review": None,
                    },
                )()
            attempts.append(attempt)
            bindings[episode.episode_id] = self._binding(
                episode, account_id=account_id, mode=mode
            )
            status = getattr(attempt, "status", "FAILED")
            if status == STATUS_SUCCEEDED:
                summary["attempts_succeeded"] += 1
                summary["reviewed_episode_ids"].append(episode.episode_id)
                if getattr(attempt, "usage_status", "UNKNOWN") == "KNOWN":
                    summary["usage_known"] += 1
                else:
                    summary["usage_unknown"] += 1
                continue
            summary["attempts_failed"] += 1
            error_type = str(getattr(attempt, "error_type", "") or "")
            if any(token in error_type.upper() for token in _TERMINAL_PROVIDER_ERRORS):
                terminal_error = error_type
                summary["stop_on_provider_error"] = True
                break

        summary["attempts_total"] = len(attempts)
        summary["input_failed_episode_ids"] = input_failed_ids
        if last_input_error:
            summary["error_type"] = last_input_error
        successful = [
            attempt for attempt in attempts if getattr(attempt, "status", None) == STATUS_SUCCEEDED
        ]
        publish_result: dict[str, Any] = {}
        if successful:
            if await fence():
                publish_result = await self.publisher.publish_attempts(
                    successful,
                    bindings=bindings,
                    known_at=datetime.now(UTC),
                )
        summary["publish"] = publish_result
        if publish_result:
            summary["cards"] = await self._bootstrap_cards(successful)
        else:
            summary["cards"] = {"enabled": False, "applied": 0}

        if summary["attempts_failed"] and summary["attempts_succeeded"]:
            summary["status"] = "PARTIAL"
        elif summary["attempts_succeeded"]:
            summary["status"] = "SUCCEEDED"
        else:
            summary["status"] = "FAILED"
        if terminal_error:
            summary["error_type"] = terminal_error
        return summary


__all__ = ["StructuredReviewRunner", "Fence"]
