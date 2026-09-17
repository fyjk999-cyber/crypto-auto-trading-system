from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import Header, HTTPException

from crypto_trader.config import Settings
from crypto_trader.ledger.service import LedgerService
from crypto_trader.market_data.service import MarketDataService
from crypto_trader.observability.audit import AuditService
from crypto_trader.order.manager import OrderManager
from crypto_trader.persistence.database import Database
from crypto_trader.portfolio.service import PortfolioService
from crypto_trader.reconciliation.service import ReconciliationService
from crypto_trader.risk.engine import RiskEngine
from crypto_trader.runtime.engine import TradingEngine
from crypto_trader.runtime.lease import LeaseManager
from crypto_trader.runtime.supervisor import TradingRuntimeSupervisor


@dataclass
class OKXConnectionState:
    provider: str = "OKX"
    environment: str = "DEMO"
    configured: bool = False
    authenticated: bool = False
    health: str = "NOT_CONFIGURED"
    key_suffix: str | None = None
    validated_at: str | None = None
    account_mode: str | None = None
    position_mode: str | None = None
    last_reason_code: str | None = None

    def configure(self, values: dict[str, str], suffix: str | None) -> None:
        self.environment = "DEMO" if values.get("OKX_DEMO", "true") == "true" else "PRODUCTION"
        self.configured = bool(
            values.get("OKX_API_KEY")
            and values.get("OKX_API_SECRET")
            and values.get("OKX_API_PASSPHRASE")
        )
        self.key_suffix = suffix
        self.authenticated = False
        self.health = "UNVERIFIED" if self.configured else "NOT_CONFIGURED"
        self.validated_at = None
        self.account_mode = None
        self.position_mode = None
        self.last_reason_code = None

    def validation(self, payload: dict) -> None:
        self.authenticated = bool(payload.get("authenticated"))
        self.health = str(payload.get("health", "DEGRADED"))
        self.last_reason_code = payload.get("reason_code")
        if self.authenticated:
            self.validated_at = datetime.now(UTC).isoformat()
            self.account_mode = payload.get("account_mode")
            self.position_mode = payload.get("position_mode")

    def snapshot(self) -> dict:
        return {
            "provider": self.provider,
            "environment": self.environment,
            "configured": self.configured,
            "authenticated": self.authenticated,
            "health": self.health,
            "key_suffix": self.key_suffix,
            "validated_at": self.validated_at,
            "account_mode": self.account_mode,
            "position_mode": self.position_mode,
            "last_reason_code": self.last_reason_code,
        }


@dataclass
class LLMRuntimeStatus:
    """Non-secret provider health for the canonical PAPER runtime."""

    provider: str = "none"
    model: str | None = None
    configured: bool = False
    reachable: bool = False
    provider_state: str = "UNKNOWN"
    configured_provider: str = "none"
    configured_model: str | None = None
    effective_provider: str | None = None
    effective_model: str | None = None
    last_success_ts: str | None = None
    last_error: str | None = None
    provider_instance: object | None = field(default=None, repr=False)

    async def probe(self) -> None:
        import os

        from crypto_trader.llm_chief.provider import (
            DeepSeekProvider,
            resolve_trading_llm_config,
            resolve_trading_model,
        )

        self.reachable = False
        self.provider_state = "UNKNOWN"
        self.configured_provider = "none"
        self.configured_model = None
        self.effective_provider = None
        self.effective_model = None
        try:
            # Provider-durability production policy: forbidden generic models
            # fail closed rather than being silently ignored.
            resolve_trading_model()
            trading_config = resolve_trading_llm_config()
        except (ValueError, RuntimeError):
            self.provider = "none"
            self.model = None
            self.configured = False
            self.provider_state = "PROVIDER_UNCONFIGURED"
            self.last_error = "FORBIDDEN_MODEL"
            return

        self.provider = (os.environ.get("LLM_PROVIDER") or trading_config.provider).lower()
        self.model = trading_config.model
        self.configured = self.provider == "deepseek" and bool(
            os.environ.get("DEEPSEEK_API_KEY")
        )
        self.last_error = None
        if not self.configured:
            self.provider_state = "PROVIDER_UNCONFIGURED"
            self.last_error = "NOT_CONFIGURED"
            return
        self.provider_state = "PROVIDER_CONFIGURED"
        self.configured_provider = trading_config.provider
        self.configured_model = trading_config.model
        provider = self.provider_instance or DeepSeekProvider()
        try:
            # Canonical health probe: real DeepSeek call with thinking + high.
            result = await provider.complete_json(
                prompt='Return only valid JSON: {"runtime_health":"ok"}',
                temperature=0.0,
                timeout_seconds=15.0,
                retries=0,
                max_tokens=512,
                thinking=True,
                reasoning_effort="high",
                operation="health_probe",
            )
        except Exception as exc:  # noqa: BLE001 - health must never crash PAPER
            self.provider_state = "PROVIDER_UNREACHABLE"
            self.last_error = "PROBE_EXCEPTION:" + type(exc).__name__
            return
        self.reachable = bool(result.ok and result.parsed_json is not None)
        self.effective_provider = result.provider or self.provider
        self.effective_model = result.model or self.model
        if self.reachable:
            self.provider_state = "PROVIDER_CONFIGURED"
            self.last_success_ts = datetime.now(UTC).isoformat()
            self.last_error = None
        else:
            self.provider_state = "PROVIDER_UNREACHABLE"
            self.last_error = result.error or "PROBE_FAILED"

    def record_probe_exception(self, exc: Exception) -> None:
        """Keep the process alive and observable when the probe itself raises."""
        self.reachable = False
        self.provider_state = "PROVIDER_UNREACHABLE"
        self.effective_provider = None
        self.effective_model = None
        self.last_error = "PROBE_EXCEPTION:" + type(exc).__name__

    def snapshot(self) -> dict:
        snapshot = {
            "provider": self.provider,
            "model": self.model,
            "configured": self.configured,
            "reachable": self.reachable,
            "provider_state": self.provider_state,
            "configured_provider": self.configured_provider,
            "configured_model": self.configured_model,
            "effective_provider": self.effective_provider,
            "effective_model": self.effective_model,
            "last_success_ts": self.last_success_ts,
            "last_error": self.last_error,
        }
        diagnostics = getattr(self.provider_instance, "diagnostics", None)
        if callable(diagnostics):
            actual = diagnostics()
            primary = actual.get("primary") or {}
            if actual.get("configured_model"):
                snapshot["model"] = actual["configured_model"]
            if actual.get("configured_provider"):
                snapshot["provider"] = actual["configured_provider"]
            decision = (
                (primary.get("operations") or {}).get("trading_decision")
                or (actual.get("operations") or {}).get("trading_decision")
                or {}
            )
            offline = actual.get("offline")
            snapshot.update(
                {
                    "config_source": actual.get("config_source"),
                    "thinking": actual.get("thinking"),
                    "reasoning_effort": actual.get("reasoning_effort"),
                    "served_by": actual.get("served_by"),
                    "decision_last_success_ts": decision.get("last_success_ts"),
                    "decision_last_error": decision.get("last_error"),
                    "decision_last_latency_ms": decision.get("last_latency_ms"),
                    "decision_last_token_usage": decision.get("last_token_usage"),
                    "decision_last_attempt_count": decision.get("last_attempt_count"),
                }
            )
            if actual.get("effective_provider") is not None:
                snapshot["effective_provider"] = actual["effective_provider"]
            if actual.get("effective_model") is not None:
                snapshot["effective_model"] = actual["effective_model"]
            if isinstance(offline, dict):
                snapshot["llm_offline_mode"] = bool(offline.get("offline"))
        if snapshot.get("model"):
            if not snapshot.get("effective_model"):
                snapshot["effective_model"] = snapshot.get("model")
            if not snapshot.get("effective_provider"):
                snapshot["effective_provider"] = snapshot.get("provider")
        return snapshot


@dataclass
class AppState:
    settings: Settings
    database: Database
    order_manager: OrderManager
    ledger: LedgerService
    portfolio: PortfolioService
    audit: AuditService
    risk: RiskEngine
    market_data: MarketDataService
    leases: LeaseManager
    reconciliation: ReconciliationService
    engine: TradingEngine | None = None
    supervisor: TradingRuntimeSupervisor | None = None
    # MASTER DIRECTIVE §29: evidence-only opportunity snapshot (no authority).
    opportunity_board: Any | None = None
    okx_connection: OKXConnectionState = field(default_factory=OKXConnectionState)
    llm_runtime: LLMRuntimeStatus = field(default_factory=LLMRuntimeStatus)


async def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings | None = None,
) -> None:
    # resolved per-request by FastAPI dependency with app state
    if settings is None:
        return
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid API key")
