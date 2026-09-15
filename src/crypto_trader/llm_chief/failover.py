"""Core LLM failover: DeepSeek -> GLM -> LLM_OFFLINE_MODE (Low-Risk V2 Phase 4).

Contract:
    DeepSeek (one immediate retry)
      -> GLM using the LATEST factual state (one immediate retry)
        -> LLM_OFFLINE_MODE with five-minute probe windows.

A stale prompt is never replayed to GLM: the caller must provide an async
``prompt_rebuilder`` that re-renders the prompt from fresh factual state. The
router is provider-only; it cannot place, size or cancel an order.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from crypto_trader.llm_chief.provider import LLMProvider, LLMResponse

OFFLINE_WINDOW_SECONDS = 300.0


class LLMLatencyTracker:
    """Bounded latency/outcome statistics per provider."""

    def __init__(self, max_samples: int = 2000) -> None:
        self.max_samples = int(max_samples)
        self.samples: dict[str, list[dict[str, Any]]] = {}

    def record(
        self,
        provider: str,
        *,
        latency_ms: float,
        ok: bool,
        timeout: bool = False,
        attempts: int = 1,
    ) -> None:
        bucket = self.samples.setdefault(provider, [])
        bucket.append(
            {
                "latency_ms": float(latency_ms),
                "ok": bool(ok),
                "timeout": bool(timeout),
                "attempts": int(attempts),
            }
        )
        if len(bucket) > self.max_samples:
            del bucket[: len(bucket) - self.max_samples]

    @staticmethod
    def _percentile(sorted_values: list[float], fraction: float) -> float:
        """Nearest-rank percentile (standard, integer-sample safe)."""
        if not sorted_values:
            return 0.0
        index = max(0, min(len(sorted_values) - 1, math.ceil(fraction * len(sorted_values)) - 1))
        return sorted_values[index]

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for provider, samples in self.samples.items():
            if not samples:
                continue
            latencies = sorted(float(item["latency_ms"]) for item in samples)
            count = len(samples)
            successes = sum(1 for item in samples if item["ok"])
            timeouts = sum(1 for item in samples if item["timeout"])
            retries = sum(1 for item in samples if int(item["attempts"]) > 1)
            out[provider] = {
                "calls": count,
                "successes": successes,
                "success_rate": successes / count,
                "timeouts": timeouts,
                "timeout_rate": timeouts / count,
                "retries": retries,
                "retry_rate": retries / count,
                "mean_ms": sum(latencies) / count,
                "p50_ms": self._percentile(latencies, 0.50),
                "p90_ms": self._percentile(latencies, 0.90),
                "p95_ms": self._percentile(latencies, 0.95),
                "p99_ms": self._percentile(latencies, 0.99),
                "max_ms": latencies[-1],
            }
        return out


@dataclass
class OfflineStatus:
    offline: bool = False
    offline_since: datetime | None = None
    next_probe_at: datetime | None = None
    windows: int = 0
    reason: str | None = None
    last_serve_provider: str | None = None
    backup_skipped_no_fresh_context: int = 0

    def as_dict(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now or datetime.now(UTC)
        return {
            "offline": self.offline,
            "offline_since": self.offline_since.isoformat() if self.offline_since else None,
            "next_probe_at": self.next_probe_at.isoformat() if self.next_probe_at else None,
            "seconds_until_probe": (
                max(0.0, (self.next_probe_at - moment).total_seconds())
                if self.next_probe_at
                else None
            ),
            "windows": self.windows,
            "reason": self.reason,
            "last_serve_provider": self.last_serve_provider,
            "backup_skipped_no_fresh_context": self.backup_skipped_no_fresh_context,
        }


class CoreLLMRouter:
    """LLMProvider-compatible DeepSeek -> GLM -> offline router.

    The Core LLM remains the only new-risk authority; this router only decides
    which provider answers a decision request.
    """

    name = "core_llm"

    def __init__(
        self,
        *,
        primary: LLMProvider,
        backup: LLMProvider | None = None,
        prompt_rebuilder: Callable[[], Awaitable[Any]] | None = None,
        offline_window_seconds: float = OFFLINE_WINDOW_SECONDS,
        tracker: LLMLatencyTracker | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.primary = primary
        self.backup = backup
        self.prompt_rebuilder = prompt_rebuilder
        self.offline_window = timedelta(seconds=max(1.0, float(offline_window_seconds)))
        self.tracker = tracker or LLMLatencyTracker()
        self._now = now or (lambda: datetime.now(UTC))
        self.status = OfflineStatus()
        self.events: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ state
    @property
    def offline(self) -> bool:
        return self.status.offline

    def healthy(self) -> bool:
        return bool(self.primary.healthy() or (self.backup and self.backup.healthy()))

    def diagnostics(self) -> dict[str, Any]:
        return {
            "router": self.name,
            "primary": getattr(self.primary, "diagnostics", lambda: {})(),
            "backup": (getattr(self.backup, "diagnostics", lambda: {})() if self.backup else None),
            "offline": self.status.as_dict(now=self._now()),
            "latency": self.tracker.snapshot(),
            "events": list(self.events[-50:]),
        }

    # -------------------------------------------------------------- completions
    async def complete_json(
        self,
        *,
        prompt: str,
        temperature: float = 0.2,
        timeout_seconds: float = 30.0,
        retries: int = 1,
        max_tokens: int = 1200,
        thinking: bool = True,
        reasoning_effort: str = "low",
        operation: str = "completion",
        state_version: str | None = None,
        prompt_rebuilder=None,
    ) -> LLMResponse:
        now = self._now()
        if self.status.offline and self.status.next_probe_at is not None:
            if now < self.status.next_probe_at:
                return self._offline_response(
                    f"offline window active until {self.status.next_probe_at.isoformat()}"
                )
            # Probe window reached: try to recover immediately with fresh facts.
            self._record_event("OFFLINE_PROBE", now)
            response = await self._attempt_chain(
                prompt=prompt,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
                retries=retries,
                max_tokens=max_tokens,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                operation=operation,
                state_version=state_version,
                rebuilder=prompt_rebuilder or self.prompt_rebuilder,
            )
            if response.ok:
                self._recover(now, response)
            else:
                self._enter_offline(now, response.error or "PROBE_FAILED")
            return response

        response = await self._attempt_chain(
            prompt=prompt,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            retries=retries,
            max_tokens=max_tokens,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            operation=operation,
            state_version=state_version,
            rebuilder=prompt_rebuilder or self.prompt_rebuilder,
        )
        if not response.ok:
            self._enter_offline(now, response.error or "ALL_PROVIDERS_FAILED")
        return response

    async def _attempt_chain(self, **kwargs) -> LLMResponse:
        rebuilder = kwargs.pop("rebuilder", self.prompt_rebuilder)
        operation = kwargs.get("operation", "completion")
        state_version = kwargs.get("state_version")
        primary_response = await self.primary.complete_json(**kwargs)
        primary_attempts = int(getattr(self.primary, "last_attempt_count", None) or 1)
        primary_response.attempts = primary_attempts
        self._record(
            getattr(self.primary, "name", "primary"),
            primary_response,
            operation=operation,
            attempts=primary_attempts,
        )
        if primary_response.ok:
            primary_response.state_version = state_version
            primary_response.served_by = getattr(self.primary, "name", "primary")
            self.status.last_serve_provider = primary_response.served_by
            return primary_response

        if self.backup is None or not self.backup.healthy():
            return self._fail(str(primary_response.error or "PRIMARY_FAILED"), state_version)

        fresh_prompt = await self._fresh_prompt(rebuilder)
        if fresh_prompt is None:
            # Constitutional rule: never replay a stale prompt to the backup.
            self.status.backup_skipped_no_fresh_context += 1
            self._record_event("BACKUP_SKIPPED_STALE_CONTEXT", self._now())
            return self._fail(
                f"{primary_response.error or 'PRIMARY_FAILED'};BACKUP_SKIPPED_NO_FRESH_CONTEXT",
                state_version,
            )
        prompt, fresh_version = fresh_prompt
        backup_kwargs = dict(kwargs)
        backup_kwargs["prompt"] = prompt
        backup_response = await self.backup.complete_json(**backup_kwargs)
        backup_attempts = int(getattr(self.backup, "last_attempt_count", None) or 1)
        backup_response.attempts = backup_attempts
        self._record(
            getattr(self.backup, "name", "backup"),
            backup_response,
            operation=operation,
            attempts=backup_attempts,
        )
        if backup_response.ok:
            backup_response.state_version = fresh_version or state_version
            backup_response.served_by = getattr(self.backup, "name", "backup")
            self.status.last_serve_provider = backup_response.served_by
            return backup_response
        return self._fail(
            "ALL_PROVIDERS_FAILED "
            f"(primary={primary_response.error}, backup={backup_response.error})",
            state_version,
        )

    async def _fresh_prompt(self, rebuilder=None) -> tuple[str, str | None] | None:
        rebuilder = rebuilder or self.prompt_rebuilder
        if rebuilder is None:
            return None
        try:
            rebuilt = await rebuilder()
        except Exception:
            return None
        if isinstance(rebuilt, tuple) and len(rebuilt) == 2:
            prompt, version = rebuilt
            return str(prompt), (str(version) if version is not None else None)
        if isinstance(rebuilt, str) and rebuilt.strip():
            return rebuilt, None
        return None

    def _record(
        self,
        provider: str,
        response: LLMResponse,
        *,
        operation: str,
        attempts: int,
    ) -> None:
        del operation  # operation-level diagnostics live on the providers
        self.tracker.record(
            provider,
            latency_ms=response.latency_ms,
            ok=response.ok,
            timeout=response.error == "LLM_TIMEOUT",
            attempts=attempts,
        )

    def _fail(self, reason: str, state_version: str | None) -> LLMResponse:
        return LLMResponse(
            text="",
            provider=self.name,
            model=self.name,
            latency_ms=0.0,
            ok=False,
            error=reason,
            state_version=state_version,
        )

    def _offline_response(self, reason: str) -> LLMResponse:
        return LLMResponse(
            text="",
            provider=self.name,
            model=self.name,
            latency_ms=0.0,
            ok=False,
            error="LLM_OFFLINE_MODE",
            state_version=None,
        )

    def _enter_offline(self, now: datetime, reason: str) -> None:
        self.status.offline = True
        self.status.offline_since = self.status.offline_since or now
        self.status.next_probe_at = now + self.offline_window
        self.status.windows += 1
        self.status.reason = reason
        self._record_event("LLM_OFFLINE_MODE", now, {"reason": reason})

    def _recover(self, now: datetime, response: LLMResponse) -> None:
        self._record_event(
            "LLM_RECOVERED",
            now,
            {"provider": response.served_by},
        )
        self.status.offline = False
        self.status.offline_since = None
        self.status.next_probe_at = None
        self.status.reason = None

    def _record_event(self, event: str, now: datetime, extra: dict | None = None) -> None:
        self.events.append({"event": event, "at": now.isoformat(), **(extra or {})})
