"""Fixtures for the LowRisk Shared Market History integration tests.

Everything here is hermetic: a fake Shared History API is served from an ephemeral
loopback port. No test touches the production service, the production data root, or
any real market data.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest


class FakeSharedHistory:
    """A configurable stand-in for the localhost Shared History API."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, object]] = {}
        self.requests: list[dict[str, object]] = []
        self.fail_all: int | None = None
        self.raw_body: str | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- lifecycle -----------------------------------------------------
    def start(self) -> str:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _handle(self) -> None:  # noqa: D401
                parsed = urlsplit(self.path)
                outer.requests.append(
                    {
                        "method": self.command,
                        "path": parsed.path,
                        "query": parse_qs(parsed.query),
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                    }
                )
                if outer.raw_body is not None:
                    body = outer.raw_body.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                status = outer.fail_all
                payload: object = {"error": "internal_error"}
                if status is None:
                    status, payload = outer.routes.get(parsed.path, (404, {"error": "not_found"}))
                body = json.dumps(payload).encode("utf-8")
                self.send_response(int(status))
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = _handle
            do_POST = _handle
            do_PUT = _handle
            do_PATCH = _handle
            do_DELETE = _handle

            def log_message(self, *args, **kwargs) -> None:  # silence test output
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def count(self, path: str | None = None) -> int:
        if path is None:
            return len(self.requests)
        return sum(1 for r in self.requests if r["path"] == path)

    @property
    def methods_seen(self) -> set[str]:
        return {str(r["method"]) for r in self.requests}


@pytest.fixture
def fake_api():
    api = FakeSharedHistory()
    yield api
    api.stop()


@pytest.fixture
def api_url(fake_api):
    return fake_api.start()


def candle_payload(rows: list[dict], coverage: str = "COMPLETE", **extra) -> dict:
    payload = {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "source": "okx",
        "schema_version": "smh.parquet.v1",
        "coverage": coverage,
        "data": rows,
        "freshness": {"status": "FRESH", "age_ms": 1000},
    }
    payload.update(extra)
    return payload


def candle_rows(start_ms: int, count: int, step_ms: int = 3_600_000) -> list[dict]:
    """Deterministic closed candles. Values are explicitly non-zero so a test can
    prove that nothing was zero-filled."""
    rows = []
    for i in range(count):
        open_time = start_ms + i * step_ms
        rows.append(
            {
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "open_time": open_time,
                "close_time": open_time + step_ms - 1,
                "open": 100.0 + i,
                "high": 110.0 + i,
                "low": 90.0 + i,
                "close": 105.0 + i,
                "volume": 12.5 + i,
                "source": "okx",
                "schema_version": "smh.parquet.v1",
            }
        )
    return rows
