"""Hierarchical learning engine: weekly/monthly/yearly aggregation.

All aggregation is deterministic code over completed child reviews. Weekly
aggregates Daily outputs, Monthly aggregates Weekly outputs, Yearly aggregates
Monthly outputs. Nothing here mutates production factor weights, strategy
state, or live configuration: results are reports plus proposal-only
recommendations.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.evolution.hierarchical.contracts import (
    MonthlyReviewResult,
    WeeklyReviewResult,
    YearlyReviewResult,
)

AVAILABLE = "AVAILABLE"
NOT_AVAILABLE = "NOT_AVAILABLE"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

# Lesson lifecycle statuses produced by weekly review.
LESSON_CONFIRMED = "CONFIRMED"
LESSON_CANDIDATE = "CANDIDATE"
LESSON_REJECTED = "REJECTED"

RECOMMENDATION_ACTIONS = (
    "KEEP",
    "INCREASE_WEIGHT_CANDIDATE",
    "DECREASE_WEIGHT_CANDIDATE",
    "FREEZE",
    "RESEARCH",
    "CHALLENGE",
    "RETIRE_CANDIDATE",
    "COMBINE_CANDIDATE",
)


def _dec(value, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        return default


def _q(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.001")))


def dedupe_child_reviews(reviews: list[dict]) -> list[dict]:
    """First occurrence per (period_id, review_id) wins; duplicates dropped."""
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for review in reviews:
        key = (str(review.get("period_id", "")), str(review.get("review_id", "")))
        if key in seen:
            continue
        seen.add(key)
        unique.append(review)
    return sorted(unique, key=lambda r: (str(r.get("period_id", "")), str(r.get("review_id", ""))))


def _iso_dates(starts_at: str, ends_at: str) -> list:
    """UTC calendar dates covered by [starts_at, ends_at], capped at 400."""
    try:
        day = datetime.fromisoformat(starts_at).astimezone(UTC).date()
        last = datetime.fromisoformat(ends_at).astimezone(UTC).date()
    except (TypeError, ValueError):
        return []
    dates: list = []
    while day <= last and len(dates) <= 400:
        dates.append(day)
        day = datetime.fromordinal(day.toordinal() + 1).date()
    return dates


def _expected_period_ids(starts_at: str, ends_at: str, granularity: str) -> list[str]:
    """Expected child period ids covered by a parent review window."""
    days = _iso_dates(starts_at, ends_at)
    if granularity == "day":
        return [day.isoformat() for day in days]
    if granularity == "week":
        weeks: list[str] = []
        for day in days:
            iso = day.isocalendar()
            label = f"{iso.year}-W{iso.week:02d}"
            if label not in weeks:
                weeks.append(label)
        return weeks
    if granularity == "month":
        months: list[str] = []
        for day in days:
            label = day.isoformat()[:7]
            if label not in months:
                months.append(label)
        return months
    return sorted({day.isoformat()[:4] for day in days})


def _recurrence_by_day(reviews: list[dict], items_key: str, label_key: str) -> dict[str, dict]:
    """Recur {label: {days, total}} across distinct child reports."""
    recurrence: dict[str, dict] = {}
    per_day: dict[str, set[str]] = defaultdict(set)
    for review in reviews:
        day = str(review.get("period_id", ""))
        for item in review.get(items_key, []) or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get(label_key, "") or item.get("category", ""))
            if not label:
                continue
            entry = recurrence.setdefault(label, {"days": 0, "total": 0})
            entry["total"] += 1
            if day and day not in per_day[label]:
                per_day[label].add(day)
                entry["days"] = len(per_day[label])
    return recurrence


def _attribution_recurrence(reviews: list[dict], field: str) -> dict[str, dict]:
    """Recur factor health issues / conflicts from factor_attributions."""
    recurrence: dict[str, dict] = {}
    per_day: dict[str, set[str]] = defaultdict(set)
    for review in reviews:
        day = str(review.get("period_id", ""))
        for attribution in review.get("factor_attributions", []) or []:
            if not isinstance(attribution, dict):
                continue
            for name in attribution.get(field, []) or []:
                label = str(name)
                entry = recurrence.setdefault(label, {"days": 0, "total": 0})
                entry["total"] += 1
                if day and day not in per_day[label]:
                    per_day[label].add(day)
                    entry["days"] = len(per_day[label])
    return recurrence


class HierarchicalLearningEngine:
    # ------------------------------------------------------------------ weekly

    def weekly_review(
        self,
        *,
        review_id: str,
        period_id: str,
        starts_at: str,
        ends_at: str,
        daily_reviews: list[dict],
    ) -> WeeklyReviewResult:
        daily_reviews = dedupe_child_reviews(daily_reviews)
        present_days = {str(d.get("period_id", "")) for d in daily_reviews}
        missing_days = [
            day
            for day in _expected_period_ids(starts_at, ends_at, "day")
            if day not in present_days
        ]
        warnings: list[str] = []
        if not daily_reviews:
            warnings.append("NO_DAILY_REPORTS")
        if missing_days:
            warnings.append("MISSING_DAILY_REPORTS:" + ",".join(missing_days))

        # Lesson lifecycle: recurrence across distinct days decides the state.
        lessons: list[dict] = []
        for daily in daily_reviews:
            for lesson in daily.get("candidate_lessons", []):
                item = dict(lesson)
                item["_day"] = daily.get("period_id", "")
                lessons.append(item)
        by_statement: dict[str, dict] = {}
        for lesson in lessons:
            statement = str(lesson.get("canonical_statement", ""))
            entry = by_statement.setdefault(
                statement, {"lesson": lesson, "days": set(), "evidence": 0, "contradiction_days": 0}
            )
            entry["days"].add(lesson.get("_day", ""))
            entry["evidence"] += int(lesson.get("evidence_count", 0) or 0)
            if _dec(lesson.get("contradictions")) > _dec(lesson.get("supporting_decisions")):
                entry["contradiction_days"] += 1
        confirmed: list[dict] = []
        candidate: list[dict] = []
        rejected: list[dict] = []
        lesson_recurrence: dict[str, dict] = {}
        for statement, entry in by_statement.items():
            lesson = entry["lesson"]
            lesson_recurrence[statement] = {
                "days": len(entry["days"]),
                "evidence": entry["evidence"],
            }
            support_days = len(entry["days"])
            # same-day repetition is NOT multi-day confirmation
            if support_days >= 2 and entry["contradiction_days"] > support_days:
                lesson["status"] = LESSON_REJECTED
                rejected.append(lesson)
            elif support_days >= 2:
                lesson["status"] = LESSON_CONFIRMED
                confirmed.append(lesson)
            else:
                lesson["status"] = LESSON_CANDIDATE
                candidate.append(lesson)
        for lesson in confirmed + candidate + rejected:
            lesson.pop("_day", None)

        patterns = [p for daily in daily_reviews for p in daily.get("patterns", [])]
        repeat_avoidable = [
            dict(p)
            for p in patterns
            if p.get("avoidable") or str(p.get("pattern_type", "")).upper() == "AVOIDABLE_ERROR"
        ]
        repeat_profitable = [
            dict(p)
            for p in patterns
            if str(p.get("pattern_type", "")).upper()
            in {"PROFITABLE", "WINNING", "GOOD_DECISION_GOOD_OUTCOME"}
        ]

        # Confidence calibration from attributions carrying confidence+outcome.
        calibration_buckets: dict[str, dict] = {}
        for daily in daily_reviews:
            for attribution in daily.get("factor_attributions", []) or []:
                if not isinstance(attribution, dict):
                    continue
                outcome = str(attribution.get("outcome_quality", ""))
                confidence = attribution.get("confidence")
                if not outcome or confidence in (None, ""):
                    continue
                bucket = calibration_buckets.setdefault(
                    outcome, {"count": 0, "confidence_sum": Decimal("0")}
                )
                bucket["count"] += 1
                bucket["confidence_sum"] += _dec(confidence)
        calibration = {
            outcome: {
                "count": bucket["count"],
                "average_confidence": _q(bucket["confidence_sum"] / Decimal(bucket["count"])),
            }
            for outcome, bucket in sorted(calibration_buckets.items())
        }

        # Drawdown over the ordered daily net pnl series.
        day_pnls = [(str(d.get("period_id", "")), _dec(d.get("net_pnl"))) for d in daily_reviews]
        running = peak = drawdown = Decimal("0")
        for _day, pnl in day_pnls:
            running += pnl
            peak = max(peak, running)
            drawdown = min(drawdown, running - peak)

        regime_weakness: dict[str, list[str]] = defaultdict(list)
        strategy_scores: dict[str, list[Decimal]] = defaultdict(list)
        factor_scores: dict[str, list[Decimal]] = defaultdict(list)
        for daily in daily_reviews:
            for regime, note in (daily.get("regime_summary") or {}).items():
                regime_weakness[str(regime)].append(str(note))
            for strategy, score in (daily.get("strategy_quality") or {}).items():
                strategy_scores[str(strategy)].append(_dec(score))
            for factor, score in (daily.get("factor_quality") or {}).items():
                factor_scores[str(factor)].append(_dec(score))

        def consistency(scores: dict[str, list[Decimal]]) -> dict:
            summary = {}
            for name in sorted(scores):
                values = scores[name]
                mean = sum(values, Decimal("0")) / Decimal(len(values))
                summary[name] = {
                    "mean": _q(mean),
                    "spread": _q(max(values) - min(values)),
                    "observations": len(values),
                }
            return summary

        return WeeklyReviewResult(
            review_id=review_id,
            period_id=period_id,
            starts_at=starts_at,
            ends_at=ends_at,
            daily_review_ids=[d.get("review_id", "") for d in daily_reviews],
            trade_count=sum(int(d.get("trade_count", 0) or 0) for d in daily_reviews),
            decision_count=sum(int(d.get("decision_count", 0) or 0) for d in daily_reviews),
            weekly_pnl=str(sum((pnl for _, pnl in day_pnls), Decimal("0"))),
            weekly_drawdown=str(drawdown),
            confirmed_lessons=confirmed,
            candidate_lessons=candidate,
            invalidated_lessons=rejected,
            persistent_patterns=[p for p in patterns if int(p.get("evidence_count", 0) or 0) >= 2],
            warnings=sorted(set(warnings)),
            daily_report_count=len(daily_reviews),
            lesson_recurrence=lesson_recurrence,
            failure_class_recurrence=_recurrence_by_day(
                daily_reviews, "error_clusters", "category"
            ),
            factor_issue_recurrence=_attribution_recurrence(daily_reviews, "health_issues"),
            factor_conflict_recurrence=_attribution_recurrence(daily_reviews, "conflicts"),
            regime_weakness={regime: notes for regime, notes in sorted(regime_weakness.items())},
            strategy_consistency=consistency(strategy_scores),
            factor_consistency=consistency(factor_scores),
            confidence_calibration=calibration,
            repeat_profitable_patterns=repeat_profitable,
            repeat_avoidable_error_patterns=repeat_avoidable,
        )

    # ----------------------------------------------------------------- monthly

    def monthly_review(
        self,
        *,
        review_id: str,
        period_id: str,
        starts_at: str,
        ends_at: str,
        weekly_reviews: list[dict],
    ) -> MonthlyReviewResult:
        weekly_reviews = dedupe_child_reviews(weekly_reviews)
        present = {str(w.get("period_id", "")) for w in weekly_reviews}
        missing_weeks = [
            label
            for label in _expected_period_ids(starts_at, ends_at, "week")
            if label not in present
        ]
        warnings: list[str] = []
        if not weekly_reviews:
            warnings.append("NO_WEEKLY_REPORTS")
        if missing_weeks:
            warnings.append("MISSING_WEEKLY_REPORTS:" + ",".join(missing_weeks))

        strategy_evaluations = [
            summary
            for weekly in weekly_reviews
            if (summary := weekly.get("strategy_quality_summary"))
        ]
        factor_evaluations = [
            summary
            for weekly in weekly_reviews
            if (summary := weekly.get("factor_quality_summary"))
        ]

        factor_usage: dict[str, int] = defaultdict(int)
        factor_failure: dict[str, int] = defaultdict(int)
        factor_conflict: dict[str, int] = defaultdict(int)
        for weekly in weekly_reviews:
            for name in weekly.get("factor_quality") or {}:
                factor_usage[name] += 1
            for name, rec in (weekly.get("factor_issue_recurrence") or {}).items():
                factor_failure[name] += int(rec.get("total", 0) or 0)
            for name, rec in (weekly.get("factor_conflict_recurrence") or {}).items():
                factor_conflict[name] += int(rec.get("total", 0) or 0)

        strategy_regime: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        factor_regime: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for weekly in weekly_reviews:
            regime = str(weekly.get("dominant_regime") or weekly.get("market_regime") or "UNKNOWN")
            for strategy, note in (weekly.get("strategy_quality_summary") or {}).items():
                strategy_regime[strategy][regime].append(str(note))
            for factor, note in (weekly.get("factor_quality_summary") or {}).items():
                factor_regime[str(factor)][regime].append(str(note))

        weekly_pnls = [_dec(w.get("weekly_pnl")) for w in weekly_reviews]
        total_pnl = sum(weekly_pnls, Decimal("0"))
        sharpe = Decimal("0")
        if len(weekly_pnls) >= 2:
            mean = total_pnl / Decimal(len(weekly_pnls))
            variance = sum(((p - mean) ** 2 for p in weekly_pnls), Decimal("0")) / Decimal(
                len(weekly_pnls)
            )
            std = variance.sqrt() if variance > 0 else Decimal("0")
            if std > 0:
                sharpe = mean / std * Decimal(len(weekly_pnls)).sqrt()
        max_drawdown = min(
            (_dec(w.get("weekly_drawdown")) for w in weekly_reviews if w.get("weekly_drawdown")),
            default=Decimal("0"),
        )
        calmar = total_pnl / abs(max_drawdown) if max_drawdown < 0 else Decimal("0")

        def _sum_optional(field: str) -> dict:
            values = [w.get(field) for w in weekly_reviews if w.get(field) is not None]
            if not values:
                return {"availability": NOT_AVAILABLE, "value": "0"}
            return {
                "availability": AVAILABLE,
                "value": str(sum((_dec(v) for v in values), Decimal("0"))),
            }

        factor_weekly_scores: dict[str, list[Decimal]] = defaultdict(list)
        for weekly in weekly_reviews:
            for factor, score in (weekly.get("factor_quality") or {}).items():
                factor_weekly_scores[str(factor)].append(_dec(score))
        factor_stability = {
            factor: _q(max(values) - min(values))
            for factor, values in sorted(factor_weekly_scores.items())
        }
        redundancy = {
            factor: {"weeks_observed": count}
            for factor, count in sorted(factor_usage.items())
            if count == len(weekly_reviews) and count >= 2
        }

        calibration = {
            outcome: summary
            for weekly in weekly_reviews
            for outcome, summary in (weekly.get("confidence_calibration") or {}).items()
        }

        return MonthlyReviewResult(
            review_id=review_id,
            period_id=period_id,
            starts_at=starts_at,
            ends_at=ends_at,
            weekly_review_ids=[w.get("review_id", "") for w in weekly_reviews],
            strategy_evaluations=strategy_evaluations,
            factor_evaluations=factor_evaluations,
            confirmed_lessons=[
                lesson for w in weekly_reviews for lesson in w.get("confirmed_lessons", [])
            ],
            invalidated_lessons=[
                lesson for w in weekly_reviews for lesson in w.get("invalidated_lessons", [])
            ],
            strategy_proposals=self._strategy_proposals(strategy_evaluations),
            factor_proposals=self._factor_proposals(
                factor_usage=dict(factor_usage),
                failure_frequency=dict(factor_failure),
                conflict_frequency=dict(factor_conflict),
                stability=factor_stability,
                week_count=max(len(weekly_reviews), 1),
            ),
            warnings=sorted(set(warnings)),
            monthly_pnl=str(total_pnl),
            max_drawdown=str(max_drawdown),
            factor_usage=dict(factor_usage),
            factor_failure_frequency=dict(factor_failure),
            factor_conflict_frequency=dict(factor_conflict),
            strategy_regime_matrix={
                k: {r: v for r, v in dict(reg).items()} for k, reg in strategy_regime.items()
            },
            factor_regime_matrix={
                k: {r: v for r, v in dict(reg).items()} for k, reg in factor_regime.items()
            },
            confidence_calibration=calibration,
            risk_adjusted={
                "monthly_pnl": str(total_pnl),
                "sharpe_weekly": _q(sharpe),
                "max_drawdown": str(max_drawdown),
                "calmar": _q(calmar),
            },
            execution_costs={
                "fees": _sum_optional("fees"),
                "funding": _sum_optional("funding"),
                "slippage": _sum_optional("slippage"),
                "turnover": _sum_optional("turnover"),
                "capital_efficiency": _sum_optional("capital_efficiency"),
            },
            factor_stability=factor_stability,
            redundancy_indicators=redundancy,
            calculation_latency=_sum_optional("calculation_latency"),
        )

    def _factor_proposals(
        self,
        *,
        factor_usage: dict[str, int],
        failure_frequency: dict[str, int],
        conflict_frequency: dict[str, int],
        stability: dict[str, str],
        week_count: int,
    ) -> list[dict]:
        """Deterministic, proposal-only factor recommendations."""
        proposals: list[dict] = []
        for factor in sorted(set(factor_usage) | set(failure_frequency) | set(conflict_frequency)):
            usage = factor_usage.get(factor, 0)
            failures = failure_frequency.get(factor, 0)
            conflicts = conflict_frequency.get(factor, 0)
            spread = _dec(stability.get(factor))
            if usage == 0 and (failures > 0 or conflicts > 0):
                action = "FREEZE"
            elif failures >= max(usage, 1):
                action = "RETIRE_CANDIDATE"
            elif conflicts >= max(usage, 1):
                action = "CHALLENGE"
            elif failures == 0 and conflicts == 0 and usage == week_count and spread == 0:
                action = "INCREASE_WEIGHT_CANDIDATE"
            elif failures == 0 and conflicts == 0 and usage >= 1:
                action = "KEEP"
            elif spread > Decimal("1"):
                action = "DECREASE_WEIGHT_CANDIDATE"
            else:
                action = "RESEARCH"
            proposals.append(
                {
                    "factor": factor,
                    "recommendation": action,
                    "proposal_only": True,
                    "basis": {
                        "usage_weeks": usage,
                        "failures": failures,
                        "conflicts": conflicts,
                        "quality_spread": stability.get(factor, "0"),
                    },
                }
            )
        return proposals

    def _strategy_proposals(self, strategy_evaluations: list[dict]) -> list[dict]:
        scores: dict[str, list[Decimal]] = defaultdict(list)
        for evaluation in strategy_evaluations:
            if not isinstance(evaluation, dict):
                continue
            for strategy, value in evaluation.items():
                scores[str(strategy)].append(_dec(value))
        proposals: list[dict] = []
        for strategy in sorted(scores):
            values = scores[strategy]
            mean = sum(values, Decimal("0")) / Decimal(len(values))
            if mean > 0:
                action = "KEEP"
            elif mean < 0:
                action = "DECREASE_WEIGHT_CANDIDATE"
            else:
                action = "RESEARCH"
            proposals.append(
                {
                    "strategy": strategy,
                    "recommendation": action,
                    "proposal_only": True,
                    "basis": {"mean_quality": _q(mean), "observations": len(values)},
                }
            )
        return proposals

    # ------------------------------------------------------------------ yearly

    def yearly_review(
        self,
        *,
        review_id: str,
        period_id: str,
        starts_at: str,
        ends_at: str,
        monthly_reviews: list[dict],
    ) -> YearlyReviewResult:
        monthly_reviews = dedupe_child_reviews(monthly_reviews)
        present = {str(m.get("period_id", "")) for m in monthly_reviews}
        missing_months = [
            label
            for label in _expected_period_ids(starts_at, ends_at, "month")
            if label not in present
        ]
        warnings: list[str] = []
        if not monthly_reviews:
            warnings.append("NO_MONTHLY_REPORTS")
        if missing_months:
            warnings.append("MISSING_MONTHLY_REPORTS:" + ",".join(missing_months))

        monthly_pnls = [_dec(m.get("monthly_pnl")) for m in monthly_reviews]
        total = sum(monthly_pnls, Decimal("0"))
        sharpe: str = NOT_AVAILABLE
        sortino: str = NOT_AVAILABLE
        if len(monthly_pnls) >= 2:
            mean = total / Decimal(len(monthly_pnls))
            variance = sum(((p - mean) ** 2 for p in monthly_pnls), Decimal("0")) / Decimal(
                len(monthly_pnls)
            )
            std = variance.sqrt() if variance > 0 else Decimal("0")
            downside = [p for p in monthly_pnls if p < 0]
            downside_std = (
                (sum((p**2 for p in downside), Decimal("0")) / Decimal(len(monthly_pnls))).sqrt()
                if downside
                else Decimal("0")
            )
            if std > 0:
                sharpe = _q(mean / std)
            if downside_std > 0:
                sortino = _q(mean / downside_std)
        drawdowns = [m.get("max_drawdown") for m in monthly_reviews if m.get("max_drawdown")]
        max_drawdown = str(min(_dec(d) for d in drawdowns)) if drawdowns else NOT_AVAILABLE
        calmar = NOT_AVAILABLE
        if drawdowns:
            worst = min(_dec(d) for d in drawdowns)
            if worst < 0:
                calmar = _q(total / abs(worst))
        worst_month = min(monthly_pnls) if monthly_pnls else None
        tail_risk = _q(worst_month) if worst_month is not None else NOT_AVAILABLE

        confirmed_count = sum(len(m.get("confirmed_lessons") or []) for m in monthly_reviews)
        rejected_count = sum(len(m.get("invalidated_lessons") or []) for m in monthly_reviews)
        lesson_total = confirmed_count + rejected_count
        confirmation_rate = (
            _q(Decimal(confirmed_count) / Decimal(lesson_total))
            if lesson_total
            else INSUFFICIENT_EVIDENCE
        )
        rejection_rate = (
            _q(Decimal(rejected_count) / Decimal(lesson_total))
            if lesson_total
            else INSUFFICIENT_EVIDENCE
        )

        strategy_lifespan: dict[str, dict] = {}
        factor_lifespan: dict[str, dict] = {}
        for monthly in monthly_reviews:
            month = str(monthly.get("period_id", ""))
            for evaluation in monthly.get("strategy_evaluations", []) or []:
                if isinstance(evaluation, dict):
                    for strategy in evaluation:
                        entry = strategy_lifespan.setdefault(
                            str(strategy), {"first_month": month, "last_month": month, "months": 0}
                        )
                        entry["last_month"] = month
                        entry["months"] += 1
            for evaluation in monthly.get("factor_evaluations", []) or []:
                if isinstance(evaluation, dict):
                    for factor in evaluation:
                        entry = factor_lifespan.setdefault(
                            str(factor), {"first_month": month, "last_month": month, "months": 0}
                        )
                        entry["last_month"] = month
                        entry["months"] += 1

        version_lineage = [
            {
                "month": m.get("period_id", ""),
                "strategy_version": m.get("strategy_version", ""),
                "factor_set_version": m.get("factor_set_version", ""),
                "model_version": m.get("model_version", ""),
                "prompt_version": m.get("prompt_version", ""),
            }
            for m in monthly_reviews
            if m.get("strategy_version") or m.get("factor_set_version")
        ]

        reliability_trend = [
            {
                "month": m.get("period_id", ""),
                "factor_failure_frequency": m.get("factor_failure_frequency", {}),
                "factor_conflict_frequency": m.get("factor_conflict_frequency", {}),
            }
            for m in monthly_reviews
        ]
        redundancy_trend = [
            {
                "month": m.get("period_id", ""),
                "redundancy_indicators": m.get("redundancy_indicators", {}),
            }
            for m in monthly_reviews
        ]

        # Evolution pipeline stats and cost metrics are only reported when the
        # monthly inputs actually carry them; otherwise explicitly unavailable.
        pipeline_fields = (
            "candidate_count",
            "validation_count",
            "promotion_count",
            "rejection_count",
            "rollback_count",
            "research_success_rate",
        )
        pipeline: dict[str, object] = {}
        for field_name in pipeline_fields:
            values = [m.get(field_name) for m in monthly_reviews if m.get(field_name) is not None]
            if not values:
                pipeline[field_name] = NOT_AVAILABLE
            elif field_name != "research_success_rate":
                pipeline[field_name] = sum((_dec(v) for v in values), Decimal("0"))
            else:
                pipeline[field_name] = _q(
                    sum((_dec(v) for v in values), Decimal("0")) / Decimal(len(values))
                )

        availability = {
            "annual_return": AVAILABLE if monthly_reviews else NOT_AVAILABLE,
            "sharpe": AVAILABLE if sharpe != NOT_AVAILABLE else INSUFFICIENT_EVIDENCE,
            "sortino": AVAILABLE if sortino != NOT_AVAILABLE else INSUFFICIENT_EVIDENCE,
            "calmar": AVAILABLE if calmar != NOT_AVAILABLE else INSUFFICIENT_EVIDENCE,
            "max_drawdown": AVAILABLE if drawdowns else NOT_AVAILABLE,
            "tail_risk": AVAILABLE if worst_month is not None else NOT_AVAILABLE,
            "lesson_confirmation_rate": AVAILABLE if lesson_total else INSUFFICIENT_EVIDENCE,
            "version_lineage": AVAILABLE if version_lineage else NOT_AVAILABLE,
            "evolution_pipeline_stats": AVAILABLE
            if any(v != NOT_AVAILABLE for v in pipeline.values())
            else NOT_AVAILABLE,
        }

        return YearlyReviewResult(
            review_id=review_id,
            period_id=period_id,
            starts_at=starts_at,
            ends_at=ends_at,
            monthly_review_ids=[m.get("review_id", "") for m in monthly_reviews],
            annual_return=str(total),
            max_drawdown=max_drawdown,
            tail_risk=tail_risk,
            strategy_lifespan=[
                dict(entry, strategy=name) for name, entry in sorted(strategy_lifespan.items())
            ],
            factor_lifespan=[
                dict(entry, factor=name) for name, entry in sorted(factor_lifespan.items())
            ],
            version_lineage=version_lineage,
            complexity_growth=[
                {
                    "month": m.get("period_id", ""),
                    "strategies": len(m.get("strategy_evaluations", []) or []),
                    "factors": len(m.get("factor_evaluations", []) or []),
                }
                for m in monthly_reviews
            ],
            lesson_effectiveness=[
                {
                    "month": m.get("period_id", ""),
                    "confirmed": len(m.get("confirmed_lessons") or []),
                    "invalidated": len(m.get("invalidated_lessons") or []),
                }
                for m in monthly_reviews
            ],
            warnings=sorted(set(warnings)),
            sharpe=sharpe,
            sortino=sortino,
            calmar=calmar,
            lesson_confirmation_rate=confirmation_rate,
            lesson_rejection_rate=rejection_rate,
            factor_reliability_trend=reliability_trend,
            factor_redundancy_trend=redundancy_trend,
            evolution_pipeline_stats=pipeline,
            metric_availability=availability,
        )
