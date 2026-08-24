from __future__ import annotations

from dataclasses import dataclass

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


async def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings | None = None,
) -> None:
    # resolved per-request by FastAPI dependency with app state
    if settings is None:
        return
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid API key")
