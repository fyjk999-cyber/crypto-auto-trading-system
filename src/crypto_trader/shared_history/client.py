"""LowRisk read-only client for the Shared Market History localhost API.

REUSE PROVENANCE
----------------
This is the pre-existing canonical consumer client, reused rather than rewritten.
It is derived from the Shared Market History implementation:

    repository : crypto-auto-trading-system (shared-market-history project)
    source     : src/shared_market_history/clients/base.py
                 src/shared_market_history/clients/lowrisk/client.py
    source repo HEAD at reuse : 8fcb90a77705e28c308d0dd25717996a2572f5d2
    blob base.py              : 5b95f5748a29f6f6a6b8425ca4716621cf4f31b6
    blob lowrisk/client.py    : 8bb105c7ea0dddc39ba0ea673f56ce216826fc17
    sha256 base.py            : 5b19cfcd6baff353626301dc925bb51b4151e04fd277607fe902adbd7331d51d

The prior design records this client as already accepted ("Low-Risk client PASS"), so no
duplicate client implementation is created here.

DELIBERATE DELTA FROM THE SOURCE (exactly two changes, both required by the LowRisk
read-only contract):

  1. The POST transport and the three batch_* methods that used it are REMOVED.
     The LowRisk integration is GET-only; it must not expose POST/PUT/PATCH/DELETE.
  2. Loopback-only URL enforcement is added. The source client accepted any base_url;
     LowRisk must not reach an arbitrary remote host by default.

Everything else -- method names, parameter names, query construction, headers (including
X-Consumer), timeout handling, exception types and messages -- is preserved.

AUTHORITY
---------
EVIDENCE ONLY. This client reads historical market facts. It cannot create direction,
risk, positions, sizing, leverage, orders or exits, and it never writes.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_API_URL = "http://127.0.0.1:8770"

# Identifies this consumer to the Shared History service for observability only.
# It grants no permission and changes no market fact or trading behavior.
CONSUMER_HEADER = "X-Consumer"
CONSUMER_ID = "lowrisk"


class SharedHistoryClientError(RuntimeError):
    """Raised when the Shared History API cannot be read.

    Callers must map this to DATA_UNAVAILABLE. They must never substitute zeros,
    synthetic bars, or unlabelled stale history.
    """


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SharedHistoryClientError("Shared History redirects are forbidden")


def is_loopback_url(url: str) -> bool:
    """True when the URL targets the local loopback interface only."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.hostname
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class SharedHistoryClient:
    """HTTP-only, GET-only client for the local shared factual history service.

    The client never learns storage internals: it has no notion of Parquet paths,
    DuckDB paths, checkpoints, backfill, retention, compaction or writer locks.
    """

    consumer = CONSUMER_ID

    def __init__(self, base_url: str = DEFAULT_API_URL, timeout: float = 20.0):
        if not is_loopback_url(base_url):
            raise SharedHistoryClientError(
                "Shared History API must be a loopback URL; refusing " + str(base_url)
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)

    # ------------------------------------------------------------------
    # Read contract
    # ------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return self._get("/v1/health")

    def stats(self) -> dict[str, Any]:
        return self._get("/v1/stats")

    def universe(self) -> dict[str, Any]:
        return self._get("/v1/universe")

    def metadata(self, symbol: str) -> dict[str, Any]:
        return self._get("/v1/metadata/" + urllib.parse.quote(symbol.strip().upper()))

    def latest_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 300,
        as_of: int | None = None,
    ) -> dict[str, Any]:
        return self._get(
            "/v1/latest",
            {"symbol": symbol, "timeframe": timeframe, "limit": limit, "as_of": as_of},
        )

    def historical_candles(
        self,
        symbol: str,
        timeframe: str,
        start: int | None = None,
        end: int | None = None,
        limit: int = 10_000,
        as_of: int | None = None,
    ) -> dict[str, Any]:
        return self._get(
            "/v1/candles",
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "start": start,
                "end": end,
                "limit": limit,
                "as_of": as_of,
            },
        )

    def features(
        self,
        symbol: str,
        as_of: int | None = None,
        feature_set_version: str | None = None,
    ) -> dict[str, Any]:
        return self._get(
            "/v1/features/" + urllib.parse.quote(symbol.strip().upper()),
            {"as_of": as_of, "feature_set_version": feature_set_version},
        )

    def regime(self, symbol: str, as_of: int | None = None) -> dict[str, Any]:
        return self._get(
            "/v1/regime/" + urllib.parse.quote(symbol.strip().upper()), {"as_of": as_of}
        )

    def funding(self, symbol: str, limit: int = 100, as_of: int | None = None) -> dict[str, Any]:
        return self._get(
            "/v1/funding/" + urllib.parse.quote(symbol.strip().upper()),
            {"limit": limit, "as_of": as_of},
        )

    def open_interest(
        self, symbol: str, limit: int = 100, as_of: int | None = None
    ) -> dict[str, Any]:
        return self._get(
            "/v1/open-interest/" + urllib.parse.quote(symbol.strip().upper()),
            {"limit": limit, "as_of": as_of},
        )

    def analogs(
        self,
        symbol: str,
        as_of: int | None = None,
        limit: int = 20,
        horizon: str = "24h",
        feature_set_version: str | None = None,
    ) -> dict[str, Any]:
        return self._get(
            "/v1/analogs/" + urllib.parse.quote(symbol.strip().upper()),
            {
                "as_of": as_of,
                "limit": limit,
                "horizon": horizon,
                "feature_set_version": feature_set_version,
            },
        )

    def first_closed_candle_at_or_after(
        self,
        symbol: str,
        target_ms: int,
        tolerance_ms: int = 300_000,
    ) -> dict[str, Any] | None:
        rows_payload = self.historical_candles(
            symbol,
            "1m",
            start=int(target_ms) - 60_000,
            end=int(target_ms) + int(tolerance_ms) + 60_000,
            limit=10_000,
        )
        for row in rows_payload.get("data") or []:
            if int(row.get("close_time") or 0) >= int(target_ms):
                return row
        return None

    # ------------------------------------------------------------------
    # HTTP boundary (GET only)
    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {key: value for key, value in (params or {}).items() if value is not None}
        )
        url = self.base_url + path + (("?" + query) if query else "")
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "shared-market-history-client/1.0",
                CONSUMER_HEADER: self.consumer,
            },
            method="GET",
        )
        return self._execute(request)

    def _execute(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise SharedHistoryClientError(
                "Shared History API HTTP " + str(exc.code) + ": " + detail
            ) from exc
        except urllib.error.URLError as exc:
            raise SharedHistoryClientError(
                "Shared History API unreachable: " + type(exc.reason).__name__
            ) from exc
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise SharedHistoryClientError("Shared History API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise SharedHistoryClientError("Shared History API returned non-object JSON")
        return payload


class LowRiskSharedHistoryClient(SharedHistoryClient):
    """Consumer wrapper around the same shared factual API.

    Low-Risk historical output is EVIDENCE ONLY: it cannot create direction, risk,
    orders, or override Core LLM/Risk/ExecutionAuthority/Base Exit.
    """

    consumer = CONSUMER_ID
