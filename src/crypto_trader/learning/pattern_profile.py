# Factual pattern, coin-profile and compressed-experience pipeline (LEARNING_ONLY).
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from crypto_trader.learning.memory_speeds import (
    POLICY_VERSION,
    VALIDATED_MIN_OBSERVATIONS,
    VALIDATED_MIN_POST_COST_BPS,
    VALIDATED_MIN_REGIMES,
    MemoryRecord,
    classify_speed,
    sample_tier,
)
from crypto_trader.persistence.models import (
    AICoinProfileORM,
    AICompressedExperienceORM,
    AIMarketPatternORM,
    GeneralizedKnowledgeORM,
)

PATTERN_VERSION = 2
COMPRESSION_MIN_SAMPLES = 50


def strategy_from_plan(plan: dict | None) -> str:
    if not plan:
        return "UNKNOWN"
    value = str(plan.get("strategy") or "").strip()
    return value or "UNKNOWN"


@dataclass(frozen=True)
class PatternIdentity:
    asset: str
    regime: str
    strategy: str
    horizon: str
    setup_signature: str

    def key(self) -> str:
        raw = "|".join(
            (self.asset, self.regime, self.strategy, self.horizon, self.setup_signature)
        ).upper()
        return hashlib.sha1(raw.encode()).hexdigest()[:16]  # noqa: S324


def resolve_identity(episode: dict) -> PatternIdentity:
    strategy = str(episode.get("strategy") or "").strip()
    if not strategy:
        strategy = strategy_from_plan(episode.get("plan"))
    return PatternIdentity(
        asset=str(episode.get("symbol") or "UNKNOWN").upper(),
        regime=str(episode.get("regime") or "UNKNOWN").upper(),
        strategy=(strategy or "UNKNOWN").upper(),
        horizon=str(episode.get("horizon") or episode.get("maturity_horizon") or "UNKNOWN"),
        setup_signature=str(episode.get("setup_signature") or episode.get("setup") or "UNKNOWN"),
    )


def _bump(mapping: dict, key: str) -> None:
    if key:
        mapping[key] = int(mapping.get(key, 0)) + 1


class GrowthMemoryPipeline:
    authority = "LEARNING_ONLY"
    is_order = False
    can_modify_core = False

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def update_from_episode(self, episode: dict, *, reviewed: bool) -> dict:
        if not reviewed:
            return {"status": "SKIPPED_UNREVIEWED"}
        identity = resolve_identity(episode)
        key = identity.key()
        net = float(episode.get("post_cost_net_bps", episode.get("net_bps", 0.0)) or 0.0)
        win = bool(episode.get("win", net > 0))
        mfe = float(episode.get("mfe_bps", 0.0) or 0.0)
        mae = float(episode.get("mae_bps", 0.0) or 0.0)
        contradiction = bool(episode.get("contradiction", False))
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            pattern = (
                await session.execute(
                    select(AIMarketPatternORM).where(AIMarketPatternORM.pattern_key == key)
                )
            ).scalar_one_or_none()
            if pattern is None:
                pattern = AIMarketPatternORM(
                    pattern_id=key,
                    pattern_key=key,
                    regime=identity.regime,
                    strategy=identity.strategy,
                    features_json={},
                    asset=identity.asset,
                    horizon=identity.horizon,
                    setup_signature=identity.setup_signature,
                    direction=str(episode.get("direction") or "UNKNOWN").upper(),
                    source_refs_json={"episode_ids": []},
                )
                session.add(pattern)
            count = int(pattern.sample_count or 0) + 1
            pattern.sample_count = count
            pattern.wins = int(pattern.wins or 0) + (1 if win else 0)
            total = float(pattern.post_cost_expectancy_bps or 0.0) * (count - 1) + net
            pattern.post_cost_expectancy_bps = total / count
            pattern.mean_mfe_bps = (float(pattern.mean_mfe_bps or 0.0) * (count - 1) + mfe) / count
            pattern.mean_mae_bps = (float(pattern.mean_mae_bps or 0.0) * (count - 1) + mae) / count
            if contradiction:
                pattern.contradiction_count = int(pattern.contradiction_count or 0) + 1
            pattern.win_rate = Decimal(str(round(pattern.wins / count, 6)))
            pattern.sample_tier = sample_tier(count)
            record = MemoryRecord(
                key=key,
                signature=f"{identity.asset}|{identity.regime}|{identity.strategy}",
                observations=count,
                wins=int(pattern.wins or 0),
                net_bps_total=float(pattern.post_cost_expectancy_bps or 0.0) * count,
                regimes=[identity.regime],
                post_cost_expectancy_bps=float(pattern.post_cost_expectancy_bps or 0.0),
                unresolved_contradictions=int(pattern.contradiction_count or 0),
            )
            pattern.memory_speed = classify_speed(record)
            pattern.quality = min(1.0, count / 100.0) * max(
                0.0, 1.0 - min(0.5, int(pattern.contradiction_count or 0) * 0.1)
            )
            refs = dict(pattern.source_refs_json or {})
            episode_ids = list(refs.get("episode_ids", []))
            episode_ids.append(episode.get("episode_id"))
            pattern.source_refs_json = {**refs, "episode_ids": episode_ids[-50:]}
            pattern.version = int(pattern.version or 1) + 1
            pattern.updated_at = now
            profile = (
                await session.execute(
                    select(AICoinProfileORM).where(AICoinProfileORM.symbol == identity.asset)
                )
            ).scalar_one_or_none()
            if profile is None:
                profile = AICoinProfileORM(symbol=identity.asset, profile_summary="")
                session.add(profile)
            extended = dict(profile.extended_json or {})
            for bucket, value in (
                ("regimes", identity.regime),
                ("strategies", identity.strategy),
                ("exit_reasons", str(episode.get("exit_reason") or "UNKNOWN")),
                ("failure_modes", str(episode.get("failure_mode") or "NONE")),
                ("holding_time_buckets", str(episode.get("holding_time_bucket") or "UNKNOWN")),
            ):
                mapping = dict(extended.get(bucket, {}))
                _bump(mapping, value)
                extended[bucket] = mapping
            profile.extended_json = extended
            pcount = int(profile.sample_count or 0) + 1
            profile.sample_count = pcount
            profile.post_cost_expectancy_bps = (
                float(profile.post_cost_expectancy_bps or 0.0) * (pcount - 1) + net
            ) / pcount
            profile.sample_tier = sample_tier(pcount)
            profile.quality_confidence = min(1.0, pcount / 100.0)
            profile.first_sample_at = profile.first_sample_at or now
            profile.last_sample_at = now
            profile.version = int(profile.version or 1) + 1
            profile.updated_at = now
            await session.commit()
        return {
            "status": "UPDATED",
            "pattern_key": key,
            "sample_count": count,
            "sample_tier": pattern.sample_tier,
            "memory_speed": pattern.memory_speed,
            "profile_symbol": identity.asset,
            "profile_samples": pcount,
        }

    async def evaluate_generalized(
        self, *, asset: str, strategy: str, horizon: str, setup_signature: str
    ) -> dict:
        """Aggregate compatible regime patterns; never fake regime diversity."""
        async with self._session_factory() as session:
            patterns = (
                (
                    await session.execute(
                        select(AIMarketPatternORM)
                        .where(AIMarketPatternORM.asset == asset)
                        .where(AIMarketPatternORM.strategy == strategy)
                        .where(AIMarketPatternORM.horizon == horizon)
                        .where(AIMarketPatternORM.setup_signature == setup_signature)
                    )
                )
                .scalars()
                .all()
            )
        if not patterns:
            return {"status": "NOT_VALIDATED", "reasons": ["no_source_patterns"]}
        total = sum(int(p.sample_count or 0) for p in patterns)
        regimes = sorted({str(p.regime or "UNKNOWN") for p in patterns})
        contradictions = sum(int(p.contradiction_count or 0) for p in patterns)
        weighted = sum(
            float(p.post_cost_expectancy_bps or 0.0) * int(p.sample_count or 0) for p in patterns
        )
        expectancy = weighted / total if total else 0.0
        stable = bool(patterns) and all(
            float(p.post_cost_expectancy_bps or 0.0) > 0 for p in patterns
        )
        reasons = []
        if total < VALIDATED_MIN_OBSERVATIONS:
            reasons.append("insufficient_samples")
        if len(regimes) < VALIDATED_MIN_REGIMES:
            reasons.append("insufficient_regimes")
        if expectancy <= VALIDATED_MIN_POST_COST_BPS:
            reasons.append("post_cost_not_positive")
        if not stable:
            reasons.append("unstable")
        if contradictions > 0:
            reasons.append("unresolved_contradiction")
        validated = not reasons
        generalized_id = hashlib.sha1(  # noqa: S324
            f"{asset}|{strategy}|{horizon}|{setup_signature}".encode()
        ).hexdigest()[:16]
        tier = (
            "VALIDATED_KNOWLEDGE"
            if validated
            else ("CANDIDATE" if total >= COMPRESSION_MIN_SAMPLES else "PROVISIONAL")
        )
        speed = (
            "VALIDATED_KNOWLEDGE"
            if validated
            else ("PATTERN" if total >= 20 else "FAST_EXPERIENCE")
        )
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(GeneralizedKnowledgeORM).where(
                        GeneralizedKnowledgeORM.generalized_id == generalized_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = GeneralizedKnowledgeORM(generalized_id=generalized_id, version=0)
                session.add(row)
            row.asset, row.strategy, row.horizon = asset, strategy, horizon
            row.setup_signature = setup_signature
            row.sample_count = total
            row.regime_count = len(regimes)
            row.source_pattern_ids_json = [p.pattern_id for p in patterns]
            row.source_regimes_json = regimes
            row.source_episode_count = total
            row.post_cost_expectancy_bps = expectancy
            row.chronological_stability = stable
            row.contradictions = contradictions
            row.quality = min(1.0, total / 100.0) * (0.0 if contradictions else 1.0)
            row.sample_tier = tier
            row.memory_speed = speed
            row.version = int(row.version or 0) + 1
            row.available_at = now
            row.updated_at = now
            await session.commit()
        return {
            "status": "VALIDATED" if validated else "NOT_VALIDATED",
            "generalized_id": generalized_id,
            "reasons": reasons,
            "sample_count": total,
            "regime_count": len(regimes),
            "sample_tier": tier,
            "memory_speed": speed,
            "available_at": now.isoformat(),
        }

    async def compress(self, pattern_key: str) -> dict:
        async with self._session_factory() as session:
            pattern = (
                await session.execute(
                    select(AIMarketPatternORM).where(AIMarketPatternORM.pattern_key == pattern_key)
                )
            ).scalar_one_or_none()
            if pattern is None:
                return {"status": "NOT_ELIGIBLE", "reasons": ["missing_pattern"]}
            reasons = []
            if int(pattern.sample_count or 0) < COMPRESSION_MIN_SAMPLES:
                reasons.append("insufficient_samples")
            if float(pattern.post_cost_expectancy_bps or 0.0) <= 0:
                reasons.append("post_cost_not_positive")
            if int(pattern.contradiction_count or 0) > 0:
                reasons.append("unresolved_contradiction")
            if reasons:
                return {"status": "NOT_ELIGIBLE", "reasons": reasons}
            version = int(pattern.version or 1)
            rule_id = f"cmp-{pattern_key}-v{version}"
            existing = (
                await session.execute(
                    select(AICompressedExperienceORM).where(
                        AICompressedExperienceORM.rule_id == rule_id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return {"status": "ALREADY_COMPRESSED", "rule_id": rule_id}
            content = (
                f"Pattern {pattern.asset} {pattern.strategy} {pattern.horizon} "
                f"setup={pattern.setup_signature}; sample_tier={pattern.sample_tier} "
                f"samples={pattern.sample_count}; "
                f"post_cost={float(pattern.post_cost_expectancy_bps):.2f}bps. "
                "UNCERTAINTY: factual evidence only, not core law; no order authority."
            )
            session.add(
                AICompressedExperienceORM(
                    rule_id=rule_id,
                    title=f"{pattern.asset} {pattern.strategy} {pattern.horizon}"[:200],
                    content=content,
                    source_episode_count=int(pattern.sample_count or 0),
                    version=version,
                    source_pattern_ids_json=[pattern_key],
                    sample_tier=pattern.sample_tier,
                    regime_coverage=1,
                    post_cost_expectancy_bps=float(pattern.post_cost_expectancy_bps or 0.0),
                    stability=float(pattern.quality or 0.0),
                    contradictions=0,
                    policy_version=POLICY_VERSION,
                )
            )
            await session.commit()
            return {
                "status": "CREATED",
                "rule_id": rule_id,
                "sample_tier": pattern.sample_tier,
                "provenance": [pattern_key],
            }
