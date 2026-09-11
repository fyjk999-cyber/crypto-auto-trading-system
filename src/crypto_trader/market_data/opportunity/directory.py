"""Read-only bounded Market Directory (§7.5).

Lets the ChiefTrader inspect factual markets OUTSIDE the initial 30-symbol
selection pool. Strictly bounded:

    * paginated
    * page size capped (default 20, hard max 25)
    * page count capped (hard max 2 pages per market-selection round)
    * total rows capped by construction
    * read-only: no direction, no orders, no scheduling side effects

Symbols discovered through this path and later selected are recorded with
``selection_source = DEEPSEEK_SELECTION`` — activating the pre-existing
DEEPSEEK_SELECTION concept in the real runtime path.
"""

from __future__ import annotations

from datetime import UTC, datetime

MAX_DIRECTORY_PAGE_SIZE = 25
MAX_DIRECTORY_PAGES_PER_ROUND = 2
DEFAULT_DIRECTORY_PAGE_SIZE = 20


class MarketDirectory:
    def __init__(
        self,
        *,
        board,
        page_size: int = DEFAULT_DIRECTORY_PAGE_SIZE,
        max_pages: int = MAX_DIRECTORY_PAGES_PER_ROUND,
    ) -> None:
        self.board = board
        self.page_size = max(1, min(int(page_size), MAX_DIRECTORY_PAGE_SIZE))
        self.max_pages = max(1, min(int(max_pages), MAX_DIRECTORY_PAGES_PER_ROUND))

    # ------------------------------------------------------------------ read
    def page(
        self,
        *,
        page: int = 1,
        scan_id: str | None = None,
        exclude: set[str] | None = None,
        sort: str = "estimated_turnover",
        filters: dict | None = None,
        now: datetime | None = None,
    ) -> dict:
        """One read-only bounded page of factual market identity/facts."""
        now = now or datetime.now(UTC)
        snapshot = self.board.current_snapshot()
        if snapshot is None or (scan_id is not None and snapshot.scan_id != scan_id):
            return {
                "page": int(page),
                "page_size": self.page_size,
                "page_count": 0,
                "total_rows": 0,
                "rows": [],
                "truncated": True,
                "error": "NO_CURRENT_SNAPSHOT",
                "read_only": True,
            }
        exclude = exclude or set()
        rows = [
            self._row(row, now=now)
            for row in (snapshot.observable_rows or ())
            if row.get("symbol") not in exclude
        ]
        rows = self._apply_filters(rows, filters or {})
        rows = self._sort(rows, sort=sort)
        total = len(rows)
        page_count = min(self.max_pages, max(1, -(-total // self.page_size)))
        page = max(1, int(page))
        start = (page - 1) * self.page_size
        window = rows[start : start + self.page_size]
        return {
            "page": page,
            "page_size": self.page_size,
            "page_count": page_count,
            "total_rows": total,
            "rows": window,
            "truncated": page >= page_count,
            "read_only": True,
            "scan_id": snapshot.scan_id,
            "universe_type": snapshot.universe_type,
            "execution_supported_label": "USDT linear perpetual swaps only (PAPER)",
            "note": "factual directory rows; selection here is research attention only",
        }

    def bounded_pages(
        self,
        *,
        scan_id: str,
        exclude: set[str] | None = None,
        now: datetime | None = None,
        sort: str = "estimated_turnover",
        filters: dict | None = None,
    ) -> tuple[list[dict], list[str]]:
        """At most ``max_pages`` pages, with lineage refs for the selection record."""
        pages: list[dict] = []
        refs: list[str] = []
        for index in range(1, self.max_pages + 1):
            page = self.page(
                page=index,
                scan_id=scan_id,
                exclude=exclude,
                sort=sort,
                filters=filters,
                now=now,
            )
            pages.append(page)
            refs.append(
                f"market_directory:scan_id={scan_id};page={index};"
                f"page_size={page['page_size']};rows={len(page['rows'])}"
            )
        return pages, refs

    def query_pages(
        self,
        query: dict | None,
        *,
        scan_id: str,
        exclude: set[str] | None = None,
        now: datetime | None = None,
    ) -> tuple[list[dict], list[str], dict[str, int]]:
        """Execute a bounded, structural ChiefTrader directory query.

        Hard limits are enforced here, not by the model: at most
        ``max_pages`` (<=2) pages of at most ``page_size`` (<=25) rows. The
        return value includes a symbol -> page map so directory-sourced
        selections can carry exact provenance.
        """
        query = query or {}
        sort = str(query.get("sort") or "estimated_turnover")
        if sort not in {"estimated_turnover", "abs_move", "symbol"}:
            sort = "estimated_turnover"
        allowed_filters = {"min_abs_move_pct", "min_estimated_turnover", "funding_side"}
        filters = {k: v for k, v in query.items() if k in allowed_filters and v is not None}
        pages, refs = self.bounded_pages(
            scan_id=scan_id, exclude=exclude, now=now, sort=sort, filters=filters
        )
        symbol_pages: dict[str, int] = {}
        for page in pages:
            for row in page.get("rows") or ():
                symbol = row.get("symbol")
                if symbol and symbol not in symbol_pages:
                    symbol_pages[symbol] = int(page["page"])
        return pages, refs, symbol_pages

    @staticmethod
    def _apply_filters(rows: list[dict], filters: dict) -> list[dict]:
        min_move = filters.get("min_abs_move_pct")
        min_turnover = filters.get("min_estimated_turnover")
        funding_side = filters.get("funding_side")
        filtered = rows
        if isinstance(min_move, (int, float)):
            filtered = [
                row
                for row in filtered
                if abs(row.get("price_change_24h_pct") or 0.0) >= float(min_move)
            ]
        if isinstance(min_turnover, (int, float)):
            filtered = [
                row
                for row in filtered
                if (row.get("estimated_quote_turnover_24h") or 0.0) >= float(min_turnover)
            ]
        if funding_side in {"positive", "negative"}:
            filtered = [
                row
                for row in filtered
                if row.get("funding_rate") is not None
                and (
                    (funding_side == "positive" and row["funding_rate"] > 0)
                    or (funding_side == "negative" and row["funding_rate"] < 0)
                )
            ]
        return filtered

    # -------------------------------------------------------------- internals
    def _row(self, row: dict, *, now: datetime) -> dict:
        symbol = row.get("symbol")
        coverage = self.board.coverage.as_dict(symbol) if symbol else {}
        return {
            "symbol": symbol,
            "instrument_identity": {
                "universe_type": "OKX Live USDT Perpetual Discovery Universe",
                "inst_type": "SWAP",
                "settle_ccy": "USDT",
                "execution_supported": bool(row.get("execution_supported", True)),
            },
            "last_price": row.get("last"),
            "price_change_24h_pct": row.get("price_change_24h_pct"),
            "estimated_quote_turnover_24h": row.get("vol_usd_24h"),
            "turnover_quality": "ESTIMATED" if row.get("vol_usd_24h") is not None else "MISSING",
            "funding_rate": row.get("funding_rate"),
            "funding_quality": row.get("funding_quality"),
            "open_interest": row.get("open_interest"),
            "oi_quality": row.get("oi_quality"),
            "last_observed_at": (
                coverage.get("last_successful_observation_at") or row.get("observed_at")
            ),
            "last_analyzed_at": coverage.get("last_successful_analysis_at"),
            "last_researched_at": coverage.get("last_llm_research_at"),
            "ticker_quality": row.get("ticker_quality"),
        }

    @staticmethod
    def _sort(rows: list[dict], *, sort: str) -> list[dict]:
        if sort == "symbol":
            return sorted(rows, key=lambda r: str(r.get("symbol")))
        if sort == "abs_move":
            return sorted(
                rows, key=lambda r: -abs(r.get("price_change_24h_pct") or 0.0)
            )
        return sorted(rows, key=lambda r: -(r.get("estimated_quote_turnover_24h") or 0.0))
