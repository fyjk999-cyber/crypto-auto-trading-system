"""Safe classification of a recovery-time order lookup failure.

    ORDER NOT FOUND  !=  ORDER NEVER EXISTED

The base candidate treated ``OrderNotFound`` as proof that an order never reached
the venue and terminalised it as REJECTED. That is not proof: a lookup can miss a
real order through a cancellation race, a purge, a paginated or partial response,
or an inconsistent venue view. Marking such an order terminally REJECTED asserts
a fact we do not have, and in this system a false terminal state is exactly what
produces an unmanageable position (the IOST incident).

So recovery classifies BEFORE it acts, and only ONE class is allowed to
terminalise:

    A  PROVEN_PRE_BROKER      -> REJECTED          (positive proof required)
    B  AMBIGUOUS              -> stay UNKNOWN
    C  BROKER_ID_MISSING      -> MISSING / reconciliation required
    D  DURABLE_FILL_PRESENT   -> preserve the factual fill, never no-order reject
    E  LOOKUP_UNREADABLE      -> stay UNKNOWN

No class resubmits: "do not wrongly terminalise" must never become "blind
resubmit".
"""

from __future__ import annotations

from dataclasses import dataclass, field

CLASS_PROVEN_PRE_BROKER = "PROVEN_PRE_BROKER"
CLASS_AMBIGUOUS = "AMBIGUOUS"
CLASS_BROKER_ID_MISSING = "BROKER_ID_MISSING"
CLASS_DURABLE_FILL_PRESENT = "DURABLE_FILL_PRESENT"
CLASS_LOOKUP_UNREADABLE = "LOOKUP_UNREADABLE"

#: Dispositions. Only TERMINAL_REJECT asserts "this order never did anything".
DISPOSITION_REJECT = "REJECTED"
DISPOSITION_UNKNOWN = "UNKNOWN"
DISPOSITION_MISSING = "MISSING"
DISPOSITION_PRESERVE_FILL = "PRESERVE_FACTUAL_FILL"

#: Reasons that the runtime raises strictly BEFORE it calls the broker, so an
#: order carrying one cannot have reached the venue. Proven in source: see
#: PaperRealMarketAdapter.submit_order, which raises these before
#: super().submit_order() is ever reached.
PROVEN_PRE_BROKER_REASONS = frozenset(
    {
        "MARKET_DATA_UNAVAILABLE",
        "MARKET_DATA_SYMBOL_MISMATCH",
    }
)

R_DURABLE_FILL = "DURABLE_FILL_EXISTS"
R_BROKER_ID_PRESENT = "BROKER_ID_PRESENT_BUT_VENUE_MISSING"
R_NO_POSITIVE_PROOF = "PRE_BROKER_PROOF_ABSENT"
R_REASON_NOT_PRE_BROKER = "FAILURE_REASON_NOT_PROVEN_PRE_BROKER"
R_LINEAGE_UNPROVEN = "PRE_BROKER_LINEAGE_UNPROVEN"
R_NONZERO_FILL = "ORDER_SHOWS_NONZERO_FILLED_QUANTITY"
R_UNREADABLE = "LOOKUP_RESULT_UNREADABLE"
R_NO_IDS = "NO_ORDER_IDENTIFIERS"


@dataclass(frozen=True, slots=True)
class RecoveryClassification:
    classification: str
    disposition: str
    reason_codes: tuple[str, ...] = ()
    detail: dict = field(default_factory=dict)

    @property
    def may_terminalise_as_rejected(self) -> bool:
        return self.disposition == DISPOSITION_REJECT

    @property
    def may_resubmit(self) -> bool:
        # Never. Stated explicitly so it cannot be inferred as a loophole.
        return False


def classify_recovery_lookup_outcome(
    *,
    lookup_ok: bool,
    exchange_order_id: str | None,
    filled_quantity,
    durable_fill_count: int = 0,
    failure_reason: str | None = None,
    pre_broker_lineage_proven: bool = False,
    has_client_order_id: bool = True,
) -> RecoveryClassification:
    """Classify one recovery lookup outcome.

    Order of checks is significant: a durable fill always wins, because factual
    execution evidence outranks any "not found" answer.
    """
    reasons: list[str] = []

    # ------------------------------------------------------- D: factual fill
    if durable_fill_count > 0:
        reasons.append(R_DURABLE_FILL)
        return RecoveryClassification(
            CLASS_DURABLE_FILL_PRESENT,
            DISPOSITION_PRESERVE_FILL,
            tuple(reasons),
            {"durable_fill_count": durable_fill_count},
        )

    # -------------------------------------------------------- E: unreadable
    if not lookup_ok:
        reasons.append(R_UNREADABLE)
        return RecoveryClassification(
            CLASS_LOOKUP_UNREADABLE, DISPOSITION_UNKNOWN, tuple(reasons)
        )

    # ------------------------------------------------------ C: broker id set
    # A broker id means the order very likely did reach the venue; "not found"
    # is then a reconciliation problem, never evidence of non-existence.
    if exchange_order_id:
        reasons.append(R_BROKER_ID_PRESENT)
        return RecoveryClassification(
            CLASS_BROKER_ID_MISSING, DISPOSITION_MISSING, tuple(reasons)
        )

    if not has_client_order_id:
        reasons.append(R_NO_IDS)
        return RecoveryClassification(
            CLASS_AMBIGUOUS, DISPOSITION_UNKNOWN, tuple(reasons)
        )

    # ---------------------------------------------------- B/A: proven or not
    reason = (failure_reason or "").strip().upper()
    if not reason:
        reasons.append(R_NO_POSITIVE_PROOF)
    elif reason not in PROVEN_PRE_BROKER_REASONS:
        reasons.append(R_REASON_NOT_PRE_BROKER)
    elif not pre_broker_lineage_proven:
        reasons.append(R_LINEAGE_UNPROVEN)

    try:
        filled = 0 if filled_quantity is None else int(str(filled_quantity))
    except (TypeError, ValueError):
        filled = 1  # unreadable fill quantity is not proof of zero
    if filled != 0:
        reasons.append(R_NONZERO_FILL)

    blocking = [r for r in reasons if r]
    if (
        not exchange_order_id
        and reason in PROVEN_PRE_BROKER_REASONS
        and pre_broker_lineage_proven
        and filled == 0
    ):
        return RecoveryClassification(
            CLASS_PROVEN_PRE_BROKER, DISPOSITION_REJECT, tuple(blocking)
        )

    return RecoveryClassification(
        CLASS_AMBIGUOUS, DISPOSITION_UNKNOWN, tuple(blocking)
    )
