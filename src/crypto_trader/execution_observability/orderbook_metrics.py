"""Deterministic orderbook metrics for execution evidence.

Pure functions over an :class:`OrderBook`. No I/O, no clock, no randomness, so
the numbers are reproducible from the same book.

The point of capturing these at submit time is that the CURRENT book can never
be used later as a historical fact: once the moment passes, "what depth was
available when we tried" is unrecoverable unless it was written down.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation

from crypto_trader.market_data.orderbook import OrderBook

#: Depth levels captured as evidence. L1 alone is deliberately not treated as
#: sufficient: measured against 57 historical entries the L1 coverage vs fill
#: ratio correlation was ~0, so several levels are recorded side by side and
#: the predictive question is left to a later, data-backed phase.
DEPTH_LEVELS: tuple[int, ...] = (1, 5, 10)

#: Marker used when a value cannot be obtained. Never invent a number.
UNKNOWN = "UNKNOWN"


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


@dataclass(frozen=True, slots=True)
class OrderbookMetrics:
    """Everything §12 requires from a pre-submit book snapshot.

    String fields carry exact decimals; ``None`` means NOT OBTAINABLE and is
    surfaced verbatim rather than guessed at.
    """

    symbol: str
    best_bid: str | None
    best_ask: str | None
    mid: str | None
    spread_bps: str | None
    bid_depth_l1: str | None
    ask_depth_l1: str | None
    bid_depth_l5: str | None
    ask_depth_l5: str | None
    bid_depth_l10: str | None
    ask_depth_l10: str | None
    microprice: str | None
    orderbook_imbalance: str | None
    # Depth on the side we would CONSUME, which is the side that actually
    # determines executability: ASK depth for a LONG entry, BID for a SHORT.
    # Kept separate from the per-side L1/L5/L10 labels because "bid depth" and
    # "executable depth" are different questions and conflating them is how a
    # sizing rule ends up reading the wrong book side.
    executable_side: str | None
    executable_depth_l1: str | None
    executable_depth_l5: str | None
    executable_depth_l10: str | None
    bids: list[list[str]]
    asks: list[list[str]]
    levels_captured: int
    quality: str

    def as_dict(self) -> dict:
        return asdict(self)


def _levels(book: OrderBook, *, side: str, limit: int) -> list[list[str]]:
    """Top ``limit`` levels as [price, quantity] strings, best first."""
    try:
        rows = book.top_levels(side=side, levels=limit)
    except Exception:  # noqa: BLE001 - evidence capture must never break the caller
        return []
    # ``top_levels`` returns factual ``(price, quantity)`` tuples. They are
    # unpacked explicitly: an attribute probe on a tuple silently yields nothing,
    # which would look like "no depth" instead of "wrong accessor".
    out: list[list[str]] = []
    for level in rows:
        try:
            price, qty = level
        except (TypeError, ValueError):
            continue
        if price is None or qty is None:
            continue
        out.append([str(price), str(qty)])
    return out


def compute_orderbook_metrics(
    book: OrderBook, *, levels: int = 10, consume_side: str | None = None
) -> OrderbookMetrics:
    """Compute the §12 metric set from one book snapshot.

    ``consume_side`` names the side the order would consume (``"ASK"`` for a LONG
    entry, ``"BID"`` for a SHORT). When omitted the executable-side fields stay
    UNKNOWN rather than guessing a direction - this module never invents a side.
    """
    best_bid = book.best_bid()
    best_ask = book.best_ask()
    mid = book.mid_price()

    bid_price = _dec(getattr(best_bid, "price", None))
    ask_price = _dec(getattr(best_ask, "price", None))
    bid_qty = _dec(getattr(best_bid, "quantity", None))
    ask_qty = _dec(getattr(best_ask, "quantity", None))

    spread_bps: str | None = None
    if bid_price is not None and ask_price is not None and mid and mid > 0:
        spread_bps = str(((ask_price - bid_price) / mid) * Decimal("10000"))

    # Microprice weights each side by the OPPOSITE side's size: a heavy bid
    # queue pulls the fair price up toward the ask.
    microprice: str | None = None
    if (
        bid_price is not None
        and ask_price is not None
        and bid_qty is not None
        and ask_qty is not None
        and (bid_qty + ask_qty) > 0
    ):
        microprice = str(
            (bid_price * ask_qty + ask_price * bid_qty) / (bid_qty + ask_qty)
        )

    imbalance: str | None = None
    b1 = _dec(book.depth_quantity(side="bid", levels=1))
    a1 = _dec(book.depth_quantity(side="ask", levels=1))
    if b1 is not None and a1 is not None and (b1 + a1) > 0:
        imbalance = str((b1 - a1) / (b1 + a1))

    depths: dict[str, str | None] = {}
    for n in DEPTH_LEVELS:
        depths[f"bid_depth_l{n}"] = _str_or_none(book.depth_quantity(side="bid", levels=n))
        depths[f"ask_depth_l{n}"] = _str_or_none(book.depth_quantity(side="ask", levels=n))

    exec_side: str | None = None
    exec_depths: dict[int, str | None] = {}
    if consume_side is not None and str(consume_side).upper() in ("BID", "ASK"):
        exec_side = str(consume_side).upper()
        for n in DEPTH_LEVELS:
            exec_depths[n] = _str_or_none(
                book.depth_quantity(side=exec_side, levels=n)
            )

    bids = _levels(book, side="bid", limit=levels)
    asks = _levels(book, side="ask", limit=levels)

    # Quality is honest about what was missing: a book with no levels at all is
    # recorded as UNKNOWN rather than as a zero-depth market.
    # A book that is not HEALTHY cannot yield trustworthy depth: depth_quantity
    # fails closed on it, so the aggregate evidence must say UNKNOWN rather than
    # "OK with empty fields".
    book_status = str(getattr(book.status, "value", book.status))
    missing = [v for v in (best_bid, best_ask) if v is None]
    if not bids and not asks:
        quality = UNKNOWN
    elif book_status != "HEALTHY":
        quality = UNKNOWN
    elif missing:
        quality = "PARTIAL"
    else:
        quality = "OK"

    return OrderbookMetrics(
        symbol=str(book.symbol),
        best_bid=_str_or_none(bid_price),
        best_ask=_str_or_none(ask_price),
        mid=_str_or_none(mid),
        spread_bps=spread_bps,
        bid_depth_l1=depths["bid_depth_l1"],
        ask_depth_l1=depths["ask_depth_l1"],
        bid_depth_l5=depths["bid_depth_l5"],
        ask_depth_l5=depths["ask_depth_l5"],
        bid_depth_l10=depths["bid_depth_l10"],
        ask_depth_l10=depths["ask_depth_l10"],
        microprice=microprice,
        orderbook_imbalance=imbalance,
        executable_side=exec_side,
        executable_depth_l1=exec_depths.get(1),
        executable_depth_l5=exec_depths.get(5),
        executable_depth_l10=exec_depths.get(10),
        bids=bids,
        asks=asks,
        levels_captured=max(len(bids), len(asks)),
        quality=quality,
    )


def _str_or_none(value: object) -> str | None:
    return None if value is None else str(value)
