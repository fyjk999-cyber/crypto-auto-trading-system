"""Phase H: tool usage journal + advisory tool-utility learning.

Directive map:

* Every tool invocation in the decision pipeline is journaled with decision
  lineage (§54-§56): tool name, decision_id / llm_invocation_id, latency,
  status, bounded detail. Raw arguments are NEVER persisted (secrets/PII
  and prompt-replay hazards); only a bounded factual detail string.
* Journal failures are fail-safe: recording problems NEVER break trading
  (they are counted and logged, never silent at scale).
* Tool utility learning (§57-§62) is ADVISORY ONLY and stays factual:
  per-tool volume/error/latency plus decision-outcome pairing through
  decision_evidence -> ai_trade_episodes.lineage_json. Lessons derived from
  reports are correlation statements with explicit non-authority framing.
  Utility data must NEVER simplify to win/loss only, must NEVER gate
  trading, and must NEVER bypass RiskEngine / ExecutionAuthority.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

logger = logging.getLogger("crypto_trader.tool_journal")

KNOWN_TOOLS = (
    "factor_snapshot",
    "decision_context",
    "memory_retrieval",
    "market_observer_evidence",
    "opportunity_scan",
    "research_gateway",
)


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
    ) -> None:
        """Buffer one invocation for later flush with decision lineage.
        Never raises; buffer bounded (overflow drops oldest with a marker)."""
        try:
            if len(self._buffer) >= self._buffer_limit:
                # Bound the buffer: drop the OLDEST row, count it (auditable
                # via .dropped) — never grow unbounded.
                self._buffer.pop(0)
                self.dropped += 1
            self._buffer.append(
                {
                    "tool_name": str(tool_name)[:64],
                    "symbol": str(symbol)[:32] if symbol else None,
                    "latency_ms": max(0, int(latency_ms)),
                    "status": str(status)[:16],
                    "detail": str(detail)[:255],
                }
            )
        except Exception:
            pass

    async def flush(self, *, decision_id: str, llm_invocation_id: str | None = None) -> int:
        """Write buffered rows with decision lineage. Returns rows written."""
        buffered, self._buffer = self._buffer, []
        written = 0
        for row in buffered:
            before = self.recorded
            await self.record(
                row["tool_name"],
                decision_id=decision_id,
                llm_invocation_id=llm_invocation_id,
                symbol=row["symbol"],
                latency_ms=row["latency_ms"],
                status=row["status"],
                detail=row["detail"],
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
    ) -> None:
        """Record one invocation. Never raises. Bounded detail only."""
        try:
            now = datetime.now(UTC).replace(tzinfo=None)
            async with self.session_factory() as session:
                await session.execute(
                    text(
                        "INSERT INTO tool_invocations (invocation_uid, tool_name, "
                        "decision_id, llm_invocation_id, symbol, status, latency_ms, "
                        "detail, created_at) VALUES (:u, :t, :d, :l, :s, :st, :ms, :de, :ts)"
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

        Sections:
        - volume/errors/latency per tool (factual)
        - decision-outcome pairing via decision_evidence ->
          ai_trade_episodes.lineage_json (WIN/LOSS/OPEN counts + mean net pnl)
          labelled CORRELATION_NOT_CAUSATION; outcome data is one factual
          input among several, never a win/loss simplification.
        """
        cutoff = datetime.now(UTC).replace(tzinfo=None)
        from datetime import timedelta

        cutoff = cutoff - timedelta(hours=int(window_hours))
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT tool_name, status, latency_ms FROM tool_invocations "
                        "WHERE created_at >= :c"
                    ),
                    {"c": cutoff},
                )
            ).all()
            pairing = (
                await session.execute(
                    text(
                        "SELECT ti.tool_name, ep.result, ep.net_pnl, ep.holding_time_seconds "
                        "FROM tool_invocations ti "
                        "JOIN decision_evidence de ON de.decision_id = ti.decision_id "
                        "JOIN ai_trade_episodes ep "
                        "  ON json_extract(ep.lineage_json, '$.decision_id') = ti.decision_id "
                        "WHERE ti.created_at >= :c"
                    ),
                    {"c": cutoff},
                )
            ).all()
        per_tool: dict[str, dict] = {}
        for tool_name, status, latency_ms in rows:
            entry = per_tool.setdefault(
                tool_name, {"invocations": 0, "errors": 0, "latency_ms_total": 0}
            )
            entry["invocations"] += 1
            if str(status) != "OK":
                entry["errors"] += 1
            entry["latency_ms_total"] += int(latency_ms or 0)
        for entry in per_tool.values():
            n = entry.pop("latency_ms_total")
            entry["avg_latency_ms"] = round(n / entry["invocations"], 1)
            entry["error_rate"] = round(entry["errors"] / entry["invocations"], 4)

        outcomes: dict[str, dict[str, object]] = {}
        for tool_name, result, net_pnl, _hold in pairing:
            slot = outcomes.setdefault(
                tool_name,
                {"episodes": 0, "WIN": 0, "LOSS": 0, "net_pnl_sum": 0.0},
            )
            slot["episodes"] += 1
            slot[str(result)] = slot.get(str(result), 0) + 1
            try:
                slot["net_pnl_sum"] += float(net_pnl or 0)
            except (TypeError, ValueError):
                pass
        for slot in outcomes.values():
            slot["mean_net_pnl"] = round(
                slot.pop("net_pnl_sum") / slot["episodes"], 8
            ) if slot["episodes"] else 0.0

        return {
            "window_hours": int(window_hours),
            "generated_at": datetime.now(UTC).isoformat(),
            "per_tool": per_tool,
            "decision_outcome_pairing": outcomes,
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
        await self._journal.record(
            self._tool, latency_ms=latency_ms, status=status, detail=detail, **self._kwargs
        )
        return False
