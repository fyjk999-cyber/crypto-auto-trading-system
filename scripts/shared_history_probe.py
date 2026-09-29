#!/usr/bin/env python
"""Runtime acceptance probe for the LowRisk Shared Market History integration.

Runs the full read contract against the live localhost service and, concurrently,
samples this process's own file descriptors to prove that the integration never
holds a direct or writable descriptor on the Shared History data root.

Required results:
    LOWRISK_WRITABLE_FDS_ON_SHARED_HISTORY = 0
    LOWRISK_DIRECT_FDS_ON_SHARED_HISTORY   = 0

This probe is READ ONLY. It never writes to the data root, never acquires a writer
lock, and never mutates a checkpoint. It is safe to run against the live service.

Usage:
    python scripts/shared_history_probe.py [--seconds 45] [--url http://127.0.0.1:8770]
"""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crypto_trader.shared_history import SharedHistoryEvidence  # noqa: E402

DATA_ROOT_MARKERS = ("/Volumes/My PSSD", "SharedMarketHistory")

# Descriptor access modes (POSIX). O_RDONLY == 0, so a writable descriptor is any
# mode other than O_RDONLY.
O_ACCMODE = 0o3
O_RDONLY = 0o0
O_WRONLY = 0o1
O_RDWR = 0o2


def fd_path(fd: int) -> str | None:
    """Resolve a descriptor to its filesystem path, portably.

    Linux exposes /dev/fd as symlinks. macOS does not: readlink fails with EINVAL,
    so F_GETPATH is used instead. Without the macOS branch this probe could never
    detect a direct descriptor, and a reported 0 would be meaningless.
    """
    try:
        return os.readlink(f"/dev/fd/{fd}")
    except OSError:
        pass
    if hasattr(fcntl, "F_GETPATH"):
        buffer = ctypes.create_string_buffer(1024)  # MAXPATHLEN on macOS
        try:
            result = fcntl.fcntl(fd, fcntl.F_GETPATH, buffer)
        except (OSError, ValueError):
            return None
        raw = result if isinstance(result, (bytes, bytearray)) else buffer.raw
        decoded = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
        return decoded or None
    return None


class FdSampler:
    """Samples open descriptors, flagging any that reach the Shared History root."""

    def __init__(self, interval: float = 0.02) -> None:
        self.interval = interval
        self.direct_fd_max = 0
        self.writable_fd_max = 0
        self.direct_paths: set[str] = set()
        self.writable_paths: set[str] = set()
        self.samples = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample_once(self) -> None:
        direct = 0
        writable = 0
        try:
            fds = os.listdir("/dev/fd")
        except OSError:
            return
        for entry in fds:
            target = fd_path(int(entry))
            if target is None:
                continue
            if not any(marker in target for marker in DATA_ROOT_MARKERS):
                continue
            direct += 1
            self.direct_paths.add(target)
            try:
                flags = fcntl.fcntl(int(entry), fcntl.F_GETFL)
            except OSError:
                continue
            if (flags & O_ACCMODE) in (O_WRONLY, O_RDWR):
                writable += 1
                self.writable_paths.add(target)
        self.direct_fd_max = max(self.direct_fd_max, direct)
        self.writable_fd_max = max(self.writable_fd_max, writable)
        self.samples += 1

    def _run(self) -> None:
        while not self._stop.is_set():
            self._sample_once()
            time.sleep(self.interval)

    def __enter__(self) -> FdSampler:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


def run_contract(evidence: SharedHistoryEvidence, symbol: str) -> dict:
    calls = [
        ("health", lambda: evidence.health()),
        ("universe", lambda: evidence.universe()),
        ("latest_candles", lambda: evidence.latest_candles(symbol, "1h", limit=10)),
        ("historical_candles", lambda: evidence.historical_candles(symbol, "1h", limit=10)),
        ("features", lambda: evidence.features(symbol)),
        ("regime", lambda: evidence.regime(symbol)),
        ("funding", lambda: evidence.funding(symbol)),
        ("open_interest", lambda: evidence.open_interest(symbol)),
    ]
    results = {}
    for name, call in calls:
        try:
            results[name] = call().as_dict()
        except Exception as exc:  # pragma: no cover - probe must never crash
            results[name] = {"available": False, "status": "DATA_UNAVAILABLE", "detail": str(exc)}
    return results


def fd_access_mode(fd: int) -> str:
    """Classify a descriptor as 'r', 'w' or 'rw'."""
    try:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    except OSError:
        return "unknown"
    mode = flags & O_ACCMODE
    if mode == O_RDONLY:
        return "r"
    if mode == O_WRONLY:
        return "w"
    if mode == O_RDWR:
        return "rw"
    return "unknown"


def run_selftest(parquet_file: Path) -> dict:
    """Positive controls proving each detection mechanism can actually fire.

    Without these, a reported 0 would be indistinguishable from a sampler that
    never works. The controls never open a writable descriptor on the data root:
    direct detection is proven on a real Parquet file opened read-only, and the
    writable classifier is proven on a scratch file outside the data root.
    """
    import tempfile

    controls: dict = {"parquet_file": str(parquet_file)}

    # Control A: a direct descriptor on the data root is detected.
    sampler = FdSampler()
    try:
        with open(parquet_file, "rb") as handle:
            sampler._sample_once()
            controls["control_direct_fd_detected"] = sampler.direct_fd_max >= 1
            controls["control_direct_fd_classified_readonly"] = (
                fd_access_mode(handle.fileno()) == "r"
            )
            controls["control_direct_fd_path"] = fd_path(handle.fileno())
    except OSError as exc:
        controls["control_direct_fd_detected"] = False
        controls["control_direct_fd_error"] = str(exc)

    # Control B: the writable classifier fires -- on a scratch file, never on the
    # Shared History data root.
    with tempfile.NamedTemporaryFile() as scratch:
        controls["control_writable_fd_classified"] = fd_access_mode(scratch.fileno()) in {
            "w",
            "rw",
        }
    with open(parquet_file, "rb") as handle:
        controls["control_readonly_fd_not_writable"] = fd_access_mode(handle.fileno()) == "r"

    controls["selftest_pass"] = bool(
        controls.get("control_direct_fd_detected")
        and controls.get("control_direct_fd_classified_readonly")
        and controls.get("control_writable_fd_classified")
        and controls.get("control_readonly_fd_not_writable")
    )
    return controls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8770")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--seconds", type=float, default=45.0)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--parquet-file",
        default="/Volumes/My PSSD/SharedMarketHistory/parquet/candles/BTCUSDT/1h/2026/09.parquet",
    )
    args = parser.parse_args()

    if args.selftest:
        controls = run_selftest(Path(args.parquet_file))
        print(json.dumps(controls, indent=2))
        return 0 if controls["selftest_pass"] else 1

    evidence = SharedHistoryEvidence(enabled=True, base_url=args.url, timeout=25.0)

    report: dict = {
        "probe": "lowrisk_shared_history_runtime_probe",
        "base_url": args.url,
        "symbol": args.symbol,
        "pid": os.getpid(),
        "started_at_ms": int(time.time() * 1000),
    }
    # Embed the positive controls so a reported 0 is self-justifying.
    report["fd_detection_controls"] = run_selftest(Path(args.parquet_file))

    with FdSampler() as sampler:
        deadline = time.monotonic() + args.seconds
        passes = 0
        first = None
        while time.monotonic() < deadline:
            snapshot = run_contract(evidence, args.symbol)
            passes += 1
            if first is None:
                first = snapshot
            time.sleep(0.05)

    report["read_passes"] = passes
    report["read_contract_first_pass"] = first
    report["counters"] = evidence.counters()
    report["fd_samples"] = sampler.samples
    report["direct_fds_on_shared_history_max"] = sampler.direct_fd_max
    report["writable_fds_on_shared_history_max"] = sampler.writable_fd_max
    report["direct_fd_paths_seen"] = sorted(sampler.direct_paths)[:10]
    report["writable_fd_paths_seen"] = sorted(sampler.writable_paths)[:10]
    report["LOWRISK_WRITABLE_FDS_ON_SHARED_HISTORY"] = sampler.writable_fd_max
    report["LOWRISK_DIRECT_FDS_ON_SHARED_HISTORY"] = sampler.direct_fd_max
    report["finished_at_ms"] = int(time.time() * 1000)

    text = json.dumps(report, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())