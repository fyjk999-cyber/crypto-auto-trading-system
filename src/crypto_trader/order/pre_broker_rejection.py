"""F6.2: repair historical UNKNOWN orders that provably never reached the broker.

The bug
-------
``OrderRejected`` subclasses ``ExchangeError``, so an ``except ExchangeError``
clause listed before ``except OrderRejected`` swallowed it entirely and the
``OrderRejected`` branch was dead code. A deterministic pre-broker refusal
("no factual book") was therefore recorded as ``UNKNOWN`` instead of
``REJECTED``. Because the pending-position-action guard treats UNKNOWN as still
pending, the plan's REDUCE/EXIT path stayed blocked with nothing left to
resolve it.

Why this classifier is narrow
-----------------------------
``exchange_order_id IS NULL`` alone proves NOTHING: on a real timeout the order
may have reached the exchange before the id was persisted, and treating that as
a rejection is how a live position gets silently abandoned. So a repair requires
POSITIVE evidence that the failure happened before the broker was ever called -
the adapter raises these reasons on a code path that returns before
``super().submit_order()``.

Anything not provable stays UNKNOWN. ``UNKNOWN != REJECTED`` is the whole point.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Reasons the adapter raises BEFORE creating a broker order. Each one must be
#: justified by adapter source order (see ``PRE_BROKER_RAISE_SITES``).
REASON_MARKET_DATA_UNAVAILABLE = "MARKET_DATA_UNAVAILABLE"
REASON_MARKET_DATA_SYMBOL_MISMATCH = "MARKET_DATA_SYMBOL_MISMATCH"

PRE_BROKER_REJECTION_REASONS: tuple[str, ...] = (
    REASON_MARKET_DATA_UNAVAILABLE,
    REASON_MARKET_DATA_SYMBOL_MISMATCH,
)

#: Documentation of WHY each reason is pre-broker, with the source location that
#: proves it. Kept in code so the justification travels with the classifier.
PRE_BROKER_RAISE_SITES: dict[str, str] = {
    REASON_MARKET_DATA_UNAVAILABLE: (
        "PaperRealMarketAdapter.submit_order raises OrderRejected before "
        "return await super().submit_order(order) "
        "(src/crypto_trader/simulator/real_market_paper.py)"
    ),
    REASON_MARKET_DATA_SYMBOL_MISMATCH: (
        "PaperRealMarketAdapter.submit_order raises OrderRejected on symbol "
        "mismatch before return await super().submit_order(order)"
    ),
}

CLASSIFICATION_PRE_BROKER_REJECTION_CONFIRMED = "PRE_BROKER_REJECTION_CONFIRMED"
CLASSIFICATION_REMAINS_UNKNOWN = "REMAINS_UNKNOWN"

#: Terminal reason written when a historical UNKNOWN is repaired.
TERMINAL_REASON_PREFIX = "PRE_BROKER_REJECTION"


@dataclass(frozen=True, slots=True)
class PreBrokerClassification:
    classification: str
    reason: str
    terminal_reason: str | None
    repair_allowed: bool

    def as_dict(self) -> dict:
        return {
            "classification": self.classification,
            "reason": self.reason,
            "terminal_reason": self.terminal_reason,
            "repair_allowed": self.repair_allowed,
        }


def _unknown(reason: str) -> PreBrokerClassification:
    return PreBrokerClassification(
        classification=CLASSIFICATION_REMAINS_UNKNOWN,
        reason=reason,
        terminal_reason=None,
        repair_allowed=False,
    )


def classify_pre_broker_rejection(
    *,
    status: str,
    exchange_order_id: str | None,
    filled_quantity,
    durable_fill_count: int,
    failure_reason: str | None,
    audit_lineage_proves_pre_broker: bool,
) -> PreBrokerClassification:
    """Decide whether a historical UNKNOWN order may be terminalised REJECTED.

    Every condition must hold. The caller is responsible for supplying
    ``audit_lineage_proves_pre_broker`` from durable lineage (the audit/event
    record naming a reason that only exists on the pre-broker path), not from a
    guess.
    """
    if str(status) != "UNKNOWN":
        return _unknown("STATUS_NOT_UNKNOWN")

    if exchange_order_id:
        # A broker id exists, so the broker WAS reached.
        return _unknown("BROKER_ID_PRESENT")

    try:
        if float(str(filled_quantity if filled_quantity is not None else 0)) > 0:
            return _unknown("FILLED_QUANTITY_NONZERO")
    except (TypeError, ValueError):
        return _unknown("FILLED_QUANTITY_UNPARSEABLE")

    if durable_fill_count and durable_fill_count > 0:
        # A fill row proves the broker was reached, whatever the id column says.
        return _unknown("DURABLE_FILL_PRESENT")

    if not failure_reason:
        return _unknown("FAILURE_REASON_MISSING")

    if failure_reason not in PRE_BROKER_REJECTION_REASONS:
        return _unknown(f"FAILURE_REASON_NOT_PRE_BROKER:{failure_reason}")

    if not audit_lineage_proves_pre_broker:
        return _unknown("PRE_BROKER_LINEAGE_UNPROVEN")

    return PreBrokerClassification(
        classification=CLASSIFICATION_PRE_BROKER_REJECTION_CONFIRMED,
        reason=failure_reason,
        terminal_reason=f"{TERMINAL_REASON_PREFIX}:{failure_reason}",
        repair_allowed=True,
    )


def extract_pre_broker_reason(events) -> tuple[str | None, bool]:
    """Read the failure reason and pre-broker proof from durable order events.

    Returns ``(reason, lineage_proves_pre_broker)``. The lineage is considered
    proven only when a recorded event carries an explicit pre-broker marker:
    either the ``broker_reached: false`` flag written by the submission path, or
    an ``ORDER_UNKNOWN``/rejection event whose payload names a reason that the
    adapter can only raise on the pre-broker path.
    """
    reason: str | None = None
    proven = False
    for event in events or []:
        payload = getattr(event, "payload", None) or {}
        raw_type = getattr(event, "event_type", "") or ""
        # Enum-or-string: durable readers may hand back either form.
        etype = str(getattr(raw_type, "value", raw_type) or "")
        candidate = payload.get("reason") or payload.get("error")
        if candidate in PRE_BROKER_REJECTION_REASONS:
            reason = candidate
            if payload.get("broker_reached") is False:
                proven = True
            elif etype in ("ORDER_UNKNOWN", "ORDER_REJECTED"):
                # The reason itself is only reachable before broker creation, so
                # its presence in durable lineage IS the pre-broker proof.
                proven = True
    return reason, proven


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    order_id: str
    classification: str
    reason: str
    terminal_reason: str | None
    repaired: bool

    def as_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "classification": self.classification,
            "reason": self.reason,
            "terminal_reason": self.terminal_reason,
            "repaired": self.repaired,
        }


@dataclass
class RepairReport:
    outcomes: list = None

    def __post_init__(self) -> None:
        if self.outcomes is None:
            self.outcomes = []

    @property
    def repaired(self) -> list:
        return [o for o in self.outcomes if o.repaired]

    @property
    def skipped(self) -> list:
        return [o for o in self.outcomes if not o.repaired]

    def counts(self) -> dict:
        tally: dict[str, int] = {}
        for outcome in self.outcomes:
            tally[outcome.classification] = tally.get(outcome.classification, 0) + 1
        return tally


async def repair_pre_broker_rejections(
    *,
    order_manager,
    unresolved_orders,
    fill_counter,
    event_loader,
    terminalize,
) -> RepairReport:
    """Terminalise ONLY provably pre-broker UNKNOWN orders.

    Callers inject the durable accessors, so this function holds no session and
    writes only through ``terminalize``. It never creates a broker fact: no
    exchange id, no cancel event, no fill, no acknowledgement - the truth is
    that the broker was never reached, and fabricating otherwise would corrupt
    the ledger the rest of the system reasons from.
    """
    report = RepairReport()
    for order in unresolved_orders or []:
        raw_status = getattr(order, "status", "")
        status = str(getattr(raw_status, "value", raw_status) or "")
        if status != "UNKNOWN":
            continue
        order_id = str(getattr(order, "internal_order_id", "") or "")
        try:
            fill_count = await fill_counter(order_id)
        except Exception:
            fill_count = 1  # unknown count must not be read as "no fills"
        try:
            events = await event_loader(order_id)
        except Exception:
            events = []
        reason, proven = extract_pre_broker_reason(events)
        classification = classify_pre_broker_rejection(
            status=status,
            exchange_order_id=getattr(order, "exchange_order_id", None),
            filled_quantity=getattr(order, "filled_quantity", 0),
            durable_fill_count=fill_count,
            failure_reason=reason,
            audit_lineage_proves_pre_broker=proven,
        )
        outcome = RepairOutcome(
            order_id=order_id,
            classification=classification.classification,
            reason=classification.reason,
            terminal_reason=classification.terminal_reason,
            repaired=False,
        )
        if classification.repair_allowed:
            await terminalize(order, classification.terminal_reason or "")
            outcome = RepairOutcome(
                order_id=order_id,
                classification=classification.classification,
                reason=classification.reason,
                terminal_reason=classification.terminal_reason,
                repaired=True,
            )
        report.outcomes.append(outcome)
    return report
