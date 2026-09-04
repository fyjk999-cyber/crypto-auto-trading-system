from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

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
    last_success_ts: str | None = None
    last_error: str | None = None

    async def probe(self) -> None:
        import os

        from crypto_trader.llm_chief.provider import DeepSeekProvider

        self.provider = os.environ.get("LLM_PROVIDER", "none").lower()
        self.model = os.environ.get("LLM_MODEL")
        self.configured = self.provider == "deepseek" and bool(
            os.environ.get("DEEPSEEK_API_KEY")
        )
        self.reachable = False
        self.last_error = None
        if not self.configured:
            self.last_error = "NOT_CONFIGURED"
            return
        result = await DeepSeekProvider().complete_json(
            prompt='Return only valid JSON: {"runtime_health":"ok"}', retries=0
        )
        self.reachable = result.ok and result.parsed_json is not None
        if self.reachable:
            self.last_success_ts = datetime.now(UTC).isoformat()
        else:
            self.last_error = result.error or "PROBE_FAILED"

    def snapshot(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "configured": self.configured,
            "reachable": self.reachable,
            "last_success_ts": self.last_success_ts,
            "last_error": self.last_error,
        }


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
