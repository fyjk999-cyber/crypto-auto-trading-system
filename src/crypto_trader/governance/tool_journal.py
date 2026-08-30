"""Phase H: tool usage journal + advisory tool-utility learning.

Directive map:

* Every tool invocation in the decision pipeline is journaled with decision
  lineage (§54-§56) and the P4 bounded audit contract
  (CS-20260830-034530-P4-TOOL-LINEAGE): invocation id, tool name/version,
  decision_id / llm_invocation_id, symbol, start/end/latency, status,
  source stage, cache state, bounded summary detail and bounded error.
  Raw arguments are NEVER persisted (secrets/PII and prompt-replay
  hazards); only bounded factual fields.
* Journal failures are fail-safe: recording problems NEVER break trading
  (they are counted and logged, never silent at scale).
* Tool utility learning (§57-§62) is ADVISORY ONLY and stays factual:
  per-tool volume/error/latency/sample size, decision-outcome pairing
  through the durable Episode -> entry decision -> tool invocation link
  (immutable ``entry_decision_id``), factor analysis (regime / strategy /
  symbol), attributable token cost, decision-evidence-change marker and an
  honest information-value comparison -- all labelled
  CORRELATION_NOT_CAUSATION, CANDIDATE-only, never a gate, never a
  RiskEngine/ExecutionAuthority bypass.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

logger = logging.getLogger("crypto_trader.tool_journal")

KNOWN_TOOLS = (
    "factor_snapshot",
    "decision_context",
    "memory_retrieval",
    "market_observer_ai",
    "market_observer_evidence",
    "opportunity_scan",
    "research_gateway",
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _group_summary(rows, col: int) -> dict:
    """Aggregate factor rows by column value into factual outcome groups."""
    groups: dict[str, dict] = {}
    for row in rows:
        raw = row[col] if col < len(row) else None
        key = str(raw) if raw is not None else "NOT_RECORDED"
        if key in ("", "null"):
            key = "NOT_RECORDED"
        result = str(row[1]) if str(row[1]) in ("WIN", "LOSS", "OPEN") else "OPEN"
        try:
            pnl = float(row[2] or 0)
        except (TypeError, ValueError):
            pnl = 0.0
        slot = groups.setdefault(
            key, {"episodes": 0, "WIN": 0, "LOSS": 0, "OPEN": 0, "net_pnl_sum": 0.0}
        )
        slot["episodes"] += 1
        slot[result] = slot.get(result, 0) + 1
        slot["net_pnl_sum"] += pnl
    for slot in groups.values():
        slot["sample_size"] = slot["episodes"]
        slot["mean_net_pnl"] = round(
            slot.pop("net_pnl_sum") / slot["episodes"], 8
        )
    return groups


class ToolInvocationJournal:
    """Async, fail-safe journal of decision-pipeline tool invocations."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        self.write_failures = 0
        self.recorded = 0
        # Per-decision buffer: pipeline tool calls happen BEFORE the
        # decision_id exists; the adapter buffers rows and flushes them with
        # the decision lineage at evidence-persist time (§54 lineage).
        self._buffer: list[dict] = []
        self._buffer_limit = 100
        self.dropped = 0

    def defer(
        self,
        tool_name: str,
        *,
        symbol: str | None = None,
        latency_ms: int = 0,
        status: str = "OK",
        detail: str = "",
        tool_version: str = "",
        source: str = "",
        cache_state: str = "UNKNOWN",
        error: str = "",
        evidence_added: str = "UNKNOWN",
        llm_invocation_id: str | None = None,
    ) -> None:
        """Buffer one invocation for later flush with decision lineage.
        Never raises; buffer bounded (overflow drops oldest with a marker)."""
        try:
            if len(self._buffer) >= self._buffer_limit:
                # Bound the buffer: drop the OLDEST row, count it (auditable
                # via .dropped) — never grow unbounded.
                self._buffer.pop(0)
                self.dropped += 1
            finished = _utcnow()
            started = finished - timedelta(milliseconds=max(0, int(latency_ms)))
            self._buffer.append(
                {
                    "tool_name": str(tool_name)[:64],
                    "symbol": str(symbol)[:32] if symbol else None,
                    "latency_ms": max(0, int(latency_ms)),
                    "status": str(status)[:16],
                    "detail": str(detail)[:255],
                    "tool_version": str(tool_version)[:32],
                    "source": str(source)[:32],
                    "cache_state": str(cache_state)[:16],
                    "started_at": started,
                    "finished_at": finished,
                    "error": str(error)[:255],
                    "evidence_added": str(evidence_added)[:16],
                    # tool-level LLM invocation (e.g. the attention call);
                    # falls back to the decision-level id at flush time.
                    "llm_invocation_id": str(llm_invocation_id)[:64]
                    if llm_invocation_id
                    else None,
                }
            )
        except Exception:
            pass

    async def flush(self, *, decision_id: str, llm_invocation_id: str | None = None) -> int:
        """Write buffered rows with decision lineage. Returns rows written.

        A row carrying its OWN llm_invocation_id (a tool that made its own
        LLM call) keeps it; the decision-level id is only a fallback.
        """
        buffered, self._buffer = self._buffer, []
        written = 0
        for row in buffered:
            before = self.recorded
            await self.record(
                row["tool_name"],
                decision_id=decision_id,
                llm_invocation_id=row.get("llm_invocation_id") or llm_invocation_id,
                symbol=row["symbol"],
                latency_ms=row["latency_ms"],
                status=row["status"],
                detail=row["detail"],
                tool_version=row.get("tool_version", ""),
                source=row.get("source", ""),
                cache_state=row.get("cache_state", "UNKNOWN"),
                started_at=row.get("started_at"),
                finished_at=row.get("finished_at"),
                error=row.get("error", ""),
                evidence_added=row.get("evidence_added", "UNKNOWN"),
            )
            written += self.recorded - before
        return written

    async def record(
        self,
        tool_name: str,
        *,
        decision_id: str | None = None,
        llm_invocation_id: str | None = None,
        symbol: str | None = None,
        latency_ms: int = 0,
        status: str = "OK",
        detail: str = "",
        tool_version: str = "",
        source: str = "",
        cache_state: str = "UNKNOWN",
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error: str = "",
        evidence_added: str = "UNKNOWN",
    ) -> None:
        """Record one invocation. Never raises. Bounded factual fields only."""
        try:
            now = _utcnow()
            finished = finished_at or now
            started = started_at or (
                finished - timedelta(milliseconds=max(0, int(latency_ms)))
            )
            async with self.session_factory() as session:
                await session.execute(
                    text(
                        "INSERT INTO tool_invocations (invocation_uid, tool_name, "
                        "decision_id, llm_invocation_id, symbol, status, latency_ms, "
                        "detail, created_at, tool_version, source, cache_state, "
                        "started_at, finished_at, error, evidence_added) "
                        "VALUES (:u, :t, :d, :l, :s, :st, :ms, :de, :ts, :tv, :src, "
                        ":cache, :sa, :fa, :er, :ea)"
                    ),
                    {
                        "u": f"tool-{uuid.uuid4().hex[:26]}",
                        "t": str(tool_name)[:64],
                        "d": str(decision_id)[:64] if decision_id else None,
                        "l": str(llm_invocation_id)[:64] if llm_invocation_id else None,
                        "s": str(symbol)[:32] if symbol else None,
                        "st": str(status)[:16],
                        "ms": max(0, int(latency_ms)),
                        "de": str(detail)[:255],
                        "ts": now,
                        "tv": str(tool_version)[:32],
                        "src": str(source)[:32],
                        "cache": str(cache_state)[:16],
                        "sa": started,
                        "fa": finished,
                        "er": str(error)[:255],
                        "ea": str(evidence_added)[:16],
                    },
                )
                await session.commit()
            self.recorded += 1
        except Exception as exc:
            self.write_failures += 1
            if self.write_failures <= 10 or self.write_failures % 100 == 0:
                logger.warning(
                    "TOOL_JOURNAL_WRITE_FAILED failures=%d error=%s",
                    self.write_failures,
                    type(exc).__name__,
                )

    def timed(self, tool_name: str, **kwargs):
        """Context-manager helper: journals a sync/async call's latency.

        Usage: ``async with journal.timed("memory_retrieval", symbol=sym): ...``
        The journal failure never propagates.
        """
        return _TimedInvocation(self, tool_name, **kwargs)

    # ------------------------------------------------------------- reports
    async def utility_report(self, window_hours: int = 24) -> dict:
        """Factual per-tool utility report (advisory only).

        P4 CS-20260830-034530-P4-TOOL-LINEAGE sections:
        - per_tool: volume / errors / error_rate / avg + p95 latency /
          explicit sample size (factual)
        - decision_outcome_pairing: WIN/LOSS/OPEN + mean net pnl per tool
          through the durable Episode -> entry decision -> tool link
          (immutable ai_trade_episodes.entry_decision_id, falling back to
          the lineage_json keys recorded at trade time)
        - factor_analysis: the same pairing grouped by regime, strategy and
          symbol (from decision evidence), each with sample size
        - cost: attributable LLM token accounting per tool via the tool's
          own llm_invocation_id -> llm_usage (NOT per-tool marginal cost)
        - decision_change: evidence_added marker distribution per tool
          (did the tool contribute evidence to the decision context)
        - information_value: outcome split for decisions with tool evidence
          ADDED vs not, with explicit correlation-only framing
        """
        cutoff = _utcnow() - timedelta(hours=int(window_hours))
        episode_join = (
            "JOIN ai_trade_episodes ep ON COALESCE("
            "ep.entry_decision_id, "
            "json_extract(ep.lineage_json, '$.entry_decision_id'), "
            "json_extract(ep.lineage_json, '$.decision_id')) = ti.decision_id "
        )
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT tool_name, status, latency_ms, source, cache_state, "
                        "evidence_added FROM tool_invocations WHERE created_at >= :c"
                    ),
                    {"c": cutoff},
                )
            ).all()
            pairing = (
                await session.execute(
                    text(
                        "SELECT ti.tool_name, ep.result, ep.net_pnl, "
                        "ep.holding_time_seconds FROM tool_invocations ti "
                        "JOIN decision_evidence de ON de.decision_id = ti.decision_id "
                        + episode_join
                        + "WHERE ti.created_at >= :c"
                    ),
                    {"c": cutoff},
                )
            ).all()
            factor_rows = (
                await session.execute(
                    text(
                        "SELECT ti.tool_name, ep.result, ep.net_pnl, ep.symbol, "
                        "json_extract(de.analysis_evidence_json, '$.market_regime'), "
                        "json_extract(de.analysis_evidence_json, '$.selected_strategy'), "
                        "ti.evidence_added "
                        "FROM tool_invocations ti "
                        "JOIN decision_evidence de ON de.decision_id = ti.decision_id "
                        + episode_join
                        + "WHERE ti.created_at >= :c"
                    ),
                    {"c": cutoff},
                )
            ).all()
            cost_rows = (
                await session.execute(
                    text(
                        "SELECT ti.tool_name, COUNT(DISTINCT lu.invocation_id), "
                        "COALESCE(SUM(lu.total_tokens), 0) FROM tool_invocations ti "
                        "JOIN llm_usage lu ON lu.invocation_id = ti.llm_invocation_id "
                        "WHERE ti.created_at >= :c "
                        "GROUP BY ti.tool_name"
                    ),
                    {"c": cutoff},
                )
            ).all()
        per_tool: dict[str, dict] = {}
        for tool_name, status, latency_ms, _source, _cache, _ea in rows:
            entry = per_tool.setdefault(
                tool_name,
                {"sample_size": 0, "invocations": 0, "errors": 0, "latencies_ms": []},
            )
            entry["invocations"] += 1
            if str(status) != "OK":
                entry["errors"] += 1
            entry["latencies_ms"].append(int(latency_ms or 0))
        for entry in per_tool.values():
            lat = entry.pop("latencies_ms")
            sorted_lat = sorted(lat)
            p95 = sorted_lat[min(len(sorted_lat) - 1, int(len(sorted_lat) * 0.95))]
            entry["sample_size"] = entry["invocations"]
            entry["avg_latency_ms"] = round(sum(lat) / entry["invocations"], 1)
            entry["p95_latency_ms"] = int(p95)
            entry["error_rate"] = round(entry["errors"] / entry["invocations"], 4)

        def _outcome_slot(store: dict, tool_name: str) -> dict:
            return store.setdefault(
                tool_name,
                {
                    "episodes": 0,
                    "sample_size": 0,
                    "WIN": 0,
                    "LOSS": 0,
                    "OPEN": 0,
                    "net_pnl_sum": 0.0,
                },
            )

        outcomes: dict[str, dict[str, object]] = {}
        for tool_name, result, net_pnl, _hold in pairing:
            slot = _outcome_slot(outcomes, tool_name)
            slot["episodes"] += 1
            key = str(result) if str(result) in ("WIN", "LOSS", "OPEN") else "OPEN"
            slot[key] = slot.get(key, 0) + 1
            try:
                slot["net_pnl_sum"] += float(net_pnl or 0)
            except (TypeError, ValueError):
                pass
        for slot in outcomes.values():
            slot["sample_size"] = slot["episodes"]
            slot["mean_net_pnl"] = round(
                slot.pop("net_pnl_sum") / slot["episodes"], 8
            ) if slot["episodes"] else 0.0

        # Factor analysis: regime / strategy / symbol groupings (sampled).
        factor_analysis: dict[str, dict] = {"regime": {}, "strategy": {}, "symbol": {}}

        def _bump(group: dict, key: str, result, net_pnl) -> None:
            if key in (None, "", "null"):
                key = "NOT_RECORDED"
            slot = group.setdefault(
                str(key),
                {"episodes": 0, "WIN": 0, "LOSS": 0, "OPEN": 0, "net_pnl_sum": 0.0},
            )
            slot["episodes"] += 1
            rkey = str(result) if str(result) in ("WIN", "LOSS", "OPEN") else "OPEN"
            slot[rkey] = slot.get(rkey, 0) + 1
            try:
                slot["net_pnl_sum"] += float(net_pnl or 0)
            except (TypeError, ValueError):
                pass

        for tool_name, result, net_pnl, symbol, regime, strategy, _ea in factor_rows:
            bucket = factor_analysis.setdefault(
                "per_tool", {}
            ).setdefault(tool_name, {"regime": {}, "strategy": {}, "symbol": {}})
            _bump(bucket["regime"], str(regime), result, net_pnl)
            _bump(bucket["strategy"], str(strategy), result, net_pnl)
            _bump(bucket["symbol"], str(symbol), result, net_pnl)
        for bucket in factor_analysis.get("per_tool", {}).values():
            for group in bucket.values():
                for slot in group.values():
                    slot["sample_size"] = slot["episodes"]
                    slot["mean_net_pnl"] = round(
                        slot.pop("net_pnl_sum") / slot["episodes"], 8
                    )
        factor_analysis["global"] = {
            "regime": _group_summary(factor_rows, 4),
            "strategy": _group_summary(factor_rows, 5),
            "symbol": _group_summary(factor_rows, 3),
        }

        # Attributable token cost (tool's own LLM invocation only).
        cost = {
            tool: {
                "llm_invocations": int(invocations or 0),
                "total_tokens": int(tokens or 0),
            }
            for tool, invocations, tokens in cost_rows
        }

        # Decision-evidence change marker + honest information value.
        evidence_flags: dict[str, dict[str, int]] = {}
        outcome_by_flag: dict[str, dict[str, dict]] = {}
        for tool_name, result, net_pnl, _sym, _regime, _strategy, ea in factor_rows:
            flags = evidence_flags.setdefault(
                tool_name, {"ADDED": 0, "EMPTY": 0, "OTHER": 0}
            )
            flag = str(ea) if str(ea) in ("ADDED", "EMPTY") else "OTHER"
            flags[flag] += 1
            split = outcome_by_flag.setdefault(
                tool_name, {"ADDED": {"episodes": 0, "WIN": 0, "net_pnl_sum": 0.0},
                            "NOT_ADDED": {"episodes": 0, "WIN": 0, "net_pnl_sum": 0.0}}
            )
            target = split["ADDED"] if flag == "ADDED" else split["NOT_ADDED"]
            target["episodes"] += 1
            if str(result) == "WIN":
                target["WIN"] += 1
            try:
                target["net_pnl_sum"] += float(net_pnl or 0)
            except (TypeError, ValueError):
                pass
        for _tool_name, flags in evidence_flags.items():
            total = sum(flags.values())
            flags["sample_size"] = total
            flags["added_rate"] = round(flags["ADDED"] / total, 4) if total else 0.0
        information_value = {}
        for tool_name, split in outcome_by_flag.items():
            info: dict = {}
            for label, stats in split.items():
                n = stats["episodes"]
                info[label] = {
                    "episodes": n,
                    "win_rate": round(stats["WIN"] / n, 4) if n else None,
                    "mean_net_pnl": round(stats["net_pnl_sum"] / n, 8) if n else None,
                }
            information_value[tool_name] = info

        return {
            "window_hours": int(window_hours),
            "generated_at": datetime.now(UTC).isoformat(),
            "per_tool": per_tool,
            "decision_outcome_pairing": outcomes,
            "factor_analysis": factor_analysis,
            "cost": cost,
            "cost_note": (
                "Token totals are attributable only to tools that made their "
                "own LLM invocation; the decision-level LLM cost is shared "
                "across the decision's tool set and is NOT a per-tool "
                "marginal cost."
            ),
            "decision_change": evidence_flags,
            "information_value": information_value,
            "information_value_note": (
                "CORRELATION_NOT_CAUSATION: outcome splits are factual "
                "comparisons with small samples; CANDIDATE-only advisory "
                "evidence for calibration review. Never a trading gate, "
                "never a RiskEngine/ExecutionAuthority bypass."
            ),
            "pairing_disclaimer": (
                "CORRELATION_NOT_CAUSATION: advisory evidence for calibration "
                "and the LLM context only; no trading gate, no risk authority, "
                "never a win/loss-only simplification"
            ),
        }

    async def emit_lesson(self, report: dict) -> str | None:
        """Write ONE advisory lesson per report into the canonical lesson
        store. Explicitly non-authoritative; returns the lesson id."""
        per_tool = report.get("per_tool") or {}
        if not per_tool:
            return None
        busiest = max(per_tool.items(), key=lambda kv: kv[1]["invocations"])
        tool, stats = busiest
        pairing = (report.get("decision_outcome_pairing") or {}).get(tool)
        statement = (
            f"TOOL_UTILITY advisory: '{tool}' handled {stats['invocations']} "
            f"invocations in the last {report['window_hours']}h "
            f"(error_rate={stats['error_rate']}, avg_latency_ms="
            f"{stats['avg_latency_ms']}). "
            + (
                f"Episodes paired with its decisions: {pairing['episodes']} "
                f"(mean_net_pnl={pairing['mean_net_pnl']}) — "
                "CORRELATION_NOT_CAUSATION. "
                if pairing
                else "No completed episode pairing yet. "
            )
            + "Advisory evidence only; no trading gate, no risk bypass."
        )
        lesson_id = f"lesson-tool-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        try:
            async with self.session_factory() as session:
                now = datetime.now(UTC)
                await session.execute(
                    text(
                        "INSERT INTO learning_lessons (lesson_id, scope, type, "
                        "canonical_statement, conditions_json, recommended_action, "
                        "evidence_count, first_seen, last_seen, confidence, status, "
                        "created_at) VALUES (:i, 'GLOBAL', "
                        "'TOOL_UTILITY_ADVISORY', :s, :c, :a, :e, :fs, :ls, :cf, "
                        "'ACTIVE', :ts)"
                    ),
                    {
                        "i": lesson_id,
                        "s": statement[:500],
                        "c": json.dumps({"window_hours": report["window_hours"]}),
                        "a": "Review in next calibration window (advisory only)"[:200],
                        "e": int(stats["invocations"]),
                        "fs": now.isoformat()[:40],
                        "ls": now.isoformat()[:40],
                        "cf": 0.3,
                        "ts": now.replace(tzinfo=None),
                    },
                )
                await session.commit()
            return lesson_id
        except Exception as exc:
            logger.warning(
                "TOOL_LESSON_WRITE_FAILED error=%s", type(exc).__name__
            )
            return None


class _TimedInvocation:
    def __init__(self, journal: ToolInvocationJournal, tool_name: str, **kwargs) -> None:
        self._journal = journal
        self._tool = tool_name
        self._kwargs = kwargs
        self._start = 0.0

    async def __aenter__(self):
        self._start = time.monotonic()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        latency_ms = int((time.monotonic() - self._start) * 1000)
        status = "OK" if exc_type is None else "ERROR"
        detail = type(exc).__name__ if exc is not None else ""
        error = f"{type(exc).__name__}: {exc}"[:255] if exc is not None else ""
        await self._journal.record(
            self._tool,
            latency_ms=latency_ms,
            status=status,
            detail=detail,
            error=error,
            **self._kwargs,
        )
        return False
