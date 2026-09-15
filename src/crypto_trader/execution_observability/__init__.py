"""Execution observability v2 (Phase E0).

Observation only. Nothing in this package is imported by a decision path, so
recording execution evidence cannot change ChiefTrader decisions, sizing, Risk,
TTL or order behaviour. A failure here degrades observability and never trades.
"""

from crypto_trader.execution_observability.evidence import (
    SAMPLE_OFFSETS_SECONDS,
    EntryEvidenceStore,
)
from crypto_trader.execution_observability.orderbook_metrics import (
    OrderbookMetrics,
    compute_orderbook_metrics,
)
from crypto_trader.execution_observability.retention import (
    RetentionPlan,
    default_retention_plan,
)

__all__ = [
    "OrderbookMetrics",
    "compute_orderbook_metrics",
    "EntryEvidenceStore",
    "SAMPLE_OFFSETS_SECONDS",
    "RetentionPlan",
    "default_retention_plan",
]
