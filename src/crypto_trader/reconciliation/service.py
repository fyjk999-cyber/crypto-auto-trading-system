"""Periodic local-vs-exchange reconciliation.

Local balances/positions are ledger projections. Exchange truth comes through
an ExchangeAdapter. Severe mismatches pause new orders (execution authority
consults reconciliation health).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from crypto_trader.domain.money import D, format_decimal
from crypto_trader.ledger.projections import replay_projections
from crypto_trader.persistence.models import ReconciliationRunORM
from crypto_trader.domain.identifiers import new_id


@dataclass
class ReconciliationReport:
    run_id: str
    ok: bool
    halt: bool
    alerts: list[str] = field(default_factory=list)
    local_balances: dict = field(default_factory=dict)
    exchange_balances: dict = field(default_factory=dict)
    positions_diff: dict = field(default_factory=dict)


class ReconciliationService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def reconcile(self, adapter) -> ReconciliationReport:
        """Compare ledger projections with exchange state. Persist result."""
        run_id = new_id("recon")
        alerts: list[str] = []
        async with self.session_factory() as session:
            local = await replay_projections(session)
        exchange_balances = {b.currency: str(b.total) for b in (await adapter.get_balances())}
        local_balances = {c: str(r["total"]) for c, r in local.balances.items()}
        for currency in sorted(set(local_balances) | set(exchange_balances)):
            left = D(local_balances.get(currency, "0"))
            right = D(exchange_balances.get(currency, "0"))
            if left != right:
                alerts.append(
                    f"BALANCE_MISMATCH {currency}: local={format_decimal(left)} exchange={format_decimal(right)}"
                )

        exchange_positions = {p.symbol: p for p in (await adapter.get_positions())}
        positions_diff: dict[str, dict] = {}
        for symbol, pos in local.positions.items():
            ex = exchange_positions.get(symbol)
            ex_qty = ex.quantity if ex else Decimal("0")
            if pos.quantity != ex_qty:
                positions_diff[symbol] = {
                    "local_quantity": format_decimal(pos.quantity),
                    "exchange_quantity": format_decimal(ex_qty),
                }
                alerts.append(
                    f"POSITION_MISMATCH {symbol}: local={format_decimal(pos.quantity)} exchange={format_decimal(ex_qty)}"
                )
        for symbol in set(exchange_positions) - set(local.positions):
            ex = exchange_positions[symbol]
            positions_diff[symbol] = {"local_quantity": "0", "exchange_quantity": format_decimal(ex.quantity)}
            alerts.append(f"POSITION_ONLY_ON_EXCHANGE {symbol}: {format_decimal(ex.quantity)}")

        halt = any(a.startswith("BALANCE_MISMATCH") or a.startswith("POSITION_MISMATCH") for a in alerts)
        report = ReconciliationReport(
            run_id=run_id,
            ok=not alerts,
            halt=halt,
            alerts=alerts,
            local_balances=local_balances,
            exchange_balances=exchange_balances,
            positions_diff=positions_diff,
        )
        async with self.session_factory() as session:
            session.add(
                ReconciliationRunORM(
                    run_id=run_id,
                    compared_at=datetime.now(timezone.utc),
                    status="OK" if report.ok else "ALERT",
                    local_balances_json=local_balances,
                    exchange_balances_json=exchange_balances,
                    positions_diff_json=positions_diff,
                    alerts_json=alerts,
                )
            )
            await session.commit()
        return report
