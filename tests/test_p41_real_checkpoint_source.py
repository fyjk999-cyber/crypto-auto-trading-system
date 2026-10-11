"""Actual pinned SH implementations; all behavior I/O is temporary and guarded.

Passing reproductions confirm defects, not production admission. Strict xfails
are unsatisfied safety contracts retained until a recovery proposal is reviewed.
"""

import ast
import builtins
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

REPO = "/Users/huhongjie/Documents/ChatGPT/shared-market-history"
VERSIONS = ("25505ff15dd6acd623140d70c0a8eb216c59ea48", "b1a3f97b213d062ed70375ac7aedbd0d67745a0b")


def source(sha, relative):
    return subprocess.check_output(["git", "-C", REPO, "show", f"{sha}:{relative}"]).decode()


@pytest.fixture(params=VERSIONS)
def actual(request):
    sha = request.param
    # storage/__init__.py imports DuckDB/Parquet; bypass that initializer, not
    # the implementations under test. Settings is only a type annotation here.
    modules = {}
    for name in (
        "shared_market_history",
        "shared_market_history.storage",
        "shared_market_history.backfill",
        "shared_market_history.universe",
    ):
        module = ModuleType(name)
        module.__path__ = []
        modules[name] = module
    config = ModuleType("shared_market_history.config")
    config.Settings = SimpleNamespace
    modules[config.__name__] = config
    cli_source = source(sha, "src/shared_market_history/__main__.py")
    with patch.dict(sys.modules, modules):
        loaded = {}
        for name in (
            "storage.atomic",
            "storage.layout",
            "storage.checkpoint_store",
            "storage.writer_lease",
            "backfill.models",
        ):
            full = "shared_market_history." + name
            module = ModuleType(full)
            sys.modules[full] = module
            raw = source(sha, "src/" + full.replace(".", "/") + ".py")
            exec(compile(raw, sha + ":" + full, "exec"), module.__dict__)
            loaded[name] = module
        with tempfile.TemporaryDirectory(prefix="p41-actual-source-") as directory:
            root = Path(directory).resolve()
            settings = SimpleNamespace(
                checkpoints_root=root / "checkpoints", logs_root=root / "logs"
            )
            store = loaded["storage.checkpoint_store"].CheckpointStore(settings)
            opened = []

            def guarded(original):
                def call(path, *args, **kwargs):
                    if isinstance(path, int):
                        raise AssertionError("unexpected caller-supplied file descriptor")
                    target = Path(path).resolve()
                    assert target.is_relative_to(root), f"non-fixture open denied: {target}"
                    opened.append(str(target))
                    return original(path, *args, **kwargs)

                return call

            with (
                patch.object(builtins, "open", guarded(builtins.open)),
                patch.object(io, "open", guarded(io.open)),
                patch.object(os, "open", guarded(os.open)),
            ):
                yield SimpleNamespace(
                    sha=sha,
                    modules=loaded,
                    root=root,
                    settings=settings,
                    store=store,
                    opened=opened,
                    cli_source=cli_source,
                )


def checkpoint(actual):
    return actual.store.load("candles", "SYNTHETICUSDT", "1d")


def test_missing_load_creates_directory(actual):
    assert not actual.settings.checkpoints_root.exists()
    assert checkpoint(actual)["status"] == "NOT_STARTED"
    assert (actual.settings.checkpoints_root / "backfill").is_dir()


@pytest.mark.parametrize("bad", ["", "{broken", "[]", "null", "42"])
def test_invalid_document_returns_fresh_defaults(actual, bad):
    path = actual.store.path_for("candles", "SYNTHETICUSDT", "1d")
    path.write_text(bad)
    assert checkpoint(actual)["completed"] is False
    assert checkpoint(actual)["status"] == "NOT_STARTED"
    assert path.read_text() == bad  # observation itself does not rewrite bytes


def test_schema_types_are_not_validated(actual):
    cp = checkpoint(actual)
    cp.update(completed="false", status=123, retry_count=True)
    actual.store.save(cp)
    result = checkpoint(actual)
    assert result["completed"] == "false" and bool(result["completed"])
    assert result["status"] == 123 and result["retry_count"] is True


def test_unknown_and_historical_fields_preserved_on_success(actual):
    cp = checkpoint(actual)
    cp.update(
        restored_reason="SYNTHETIC_ORIGIN_NOT_HISTORY",
        restored_completed_at=17,
        future_control={"origin": "fixture", "flag": True},
        pause_reason="fixture pause",
    )
    actual.store.save(cp)
    actual.store.mark_success("candles", "SYNTHETICUSDT", "1d", newest_fetched=123, completed=True)
    result = checkpoint(actual)
    for key in ("restored_reason", "restored_completed_at", "future_control", "pause_reason"):
        assert result[key] == cp[key]


def test_two_stores_allow_stale_overwrite_without_cas(actual):
    first = checkpoint(actual)
    actual.store.save(first)
    stale = checkpoint(actual)
    other = type(actual.store)(actual.settings)
    fresh = checkpoint(actual)
    fresh.update(newest_fetched=200, completed=True, future_control="new")
    other.save(fresh)
    actual.store.save(stale)
    result = checkpoint(actual)
    assert result["newest_fetched"] is None and result["completed"] is False
    assert "future_control" not in result


def test_checkpoint_store_bypasses_an_unacquired_lease(actual):
    lease_type = actual.modules["storage.writer_lease"].WriterLease
    owner, rejected = lease_type(actual.settings), lease_type(actual.settings)
    assert owner.acquire()
    try:
        assert not rejected.acquire()
        cp = checkpoint(actual)
        cp["next_cursor"] = 91
        actual.store.save(cp)  # Store accepts writes despite failed ownership.
        assert checkpoint(actual)["next_cursor"] == 91
    finally:
        rejected.release()
        owner.release()


def test_directory_open_failure_is_silent_after_replace(actual):
    atomic = actual.modules["storage.atomic"]
    cp = checkpoint(actual)
    with patch.object(atomic.os, "open", side_effect=PermissionError("fixture directory denied")):
        result = actual.store.save(cp)
    assert result["status"] == "NOT_STARTED"
    assert checkpoint(actual)["updated_at"] == result["updated_at"]


def test_pre_rename_failure_retains_previous_bytes(actual):
    cp = checkpoint(actual)
    actual.store.save(cp)
    path = actual.store.path_for("candles", "SYNTHETICUSDT", "1d")
    original = path.read_bytes()
    cp["completed"] = True
    with patch.object(
        actual.modules["storage.atomic"].os, "replace", side_effect=OSError("fixture rename")
    ):
        with pytest.raises(OSError):
            actual.store.save(cp)
    assert path.read_bytes() == original
    assert not list(path.parent.glob(".*.tmp.*"))


def test_file_fsync_failure_retains_previous_bytes(actual):
    cp = checkpoint(actual)
    actual.store.save(cp)
    path = actual.store.path_for("candles", "SYNTHETICUSDT", "1d")
    original = path.read_bytes()
    with patch.object(
        actual.modules["storage.atomic"].os, "fsync", side_effect=OSError("fixture fsync")
    ):
        with pytest.raises(OSError):
            actual.store.save(cp)
    assert path.read_bytes() == original


def test_post_rename_fsync_failure_has_committed_bytes(actual):
    cp = checkpoint(actual)
    cp.update(completed=True, status="COMPLETE")
    with patch.object(
        actual.modules["storage.atomic"], "fsync_dir", side_effect=OSError("fixture dir fsync")
    ):
        with pytest.raises(OSError):
            actual.store.save(cp)
    assert checkpoint(actual)["completed"] is True
    # Current recovery operation reclassifies an already-replaced checkpoint.
    actual.store.mark_error("candles", "SYNTHETICUSDT", "1d", "fixture uncertain commit")
    assert checkpoint(actual)["status"] == "ERROR"
    assert checkpoint(actual)["completed"] is True


def test_retry_mark_error_is_not_idempotent(actual):
    checkpoint(actual)
    for _ in range(2):
        actual.store.mark_error("candles", "SYNTHETICUSDT", "1d", "same fixture failure")
    assert checkpoint(actual)["retry_count"] == 2


def test_cli_backfill_calls_real_store_without_lease(actual):
    tree = ast.parse(actual.cli_source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_backfill")
    engine_module = ModuleType("shared_market_history.backfill.engine")
    discovery_module = ModuleType("shared_market_history.universe.discovery")

    class Engine:
        def __init__(self, settings):
            assert settings is actual.settings

        def build_candle_tasks(self, *args, **kwargs):
            return ["fixture task"]

        def run(self, tasks, **kwargs):
            actual.store.save(checkpoint(actual))
            return {"errors": 0}

    class Discovery:
        def __init__(self, settings):
            self.metadata = SimpleNamespace(
                universe_size=lambda: 1,
                load_universe_state=lambda: {"symbols": [{"symbol": "SYNTHETICUSDT"}]},
            )

    engine_module.BackfillEngine = Engine
    discovery_module.UniverseDiscovery = Discovery
    namespace = {
        "Any": object,
        "argparse": SimpleNamespace(Namespace=object),
        "TIMEFRAME_MS": {"1d": 86400000},
        "json": json,
    }
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), "actual_cli_backfill", "exec"), namespace
    )
    args = SimpleNamespace(
        refresh=False,
        symbols="SYNTHETICUSDT",
        validation_symbols=False,
        all=False,
        max_symbols=0,
        timeframes="1d",
        funding=False,
        open_interest=False,
        quiet=True,
        max_pages=1,
    )
    with patch.dict(
        sys.modules,
        {engine_module.__name__: engine_module, discovery_module.__name__: discovery_module},
    ):
        assert namespace["_backfill"](actual.settings, args) == 0
    assert not actual.settings.logs_root.exists()  # no lease or lock was acquired


@pytest.mark.xfail(
    strict=True,
    reason="PROVEN_DEFECT: corrupt input is treated as fresh; recovery proposal pending",
)
def test_required_corrupt_input_rejected(actual):
    actual.store.path_for("candles", "SYNTHETICUSDT", "1d").write_text("{corrupt")
    with pytest.raises(ValueError):
        checkpoint(actual)


@pytest.mark.xfail(
    strict=True, reason="PROVEN_DEFECT: stale overwrite allowed; CAS recovery proposal pending"
)
def test_required_stale_state_rejected(actual):
    stale = checkpoint(actual)
    actual.store.mark_success("candles", "SYNTHETICUSDT", "1d", newest_fetched=10, completed=True)
    with pytest.raises(RuntimeError):
        actual.store.save(stale)


@pytest.mark.xfail(
    strict=True,
    reason="PROVEN_DEFECT: directory open failure swallowed; commit recovery proposal pending",
)
def test_required_directory_open_failure_rejected(actual):
    with patch.object(actual.modules["storage.atomic"].os, "open", side_effect=PermissionError):
        with pytest.raises(OSError):
            actual.store.save(checkpoint(actual))
