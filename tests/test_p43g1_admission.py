"""Source-only boundary probes and synthetic contract checks; not a repair."""

import ast
import json
import threading
import time
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.p42_load_reference import classify
from scripts.p43g1_admission import admit, compatibility_matrix
from tests import test_p41_real_checkpoint_source as baseline
from tests.test_p4_checkpoint_fixture import p4
from tests.test_p41_real_checkpoint_source import actual as actual

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def readers():
    paths = {
        "api": "api/service.py",
        "server": "api/server.py",
        "stats": "observability/stats.py",
        "maintenance": "maintenance.py",
    }
    return {
        sha: {
            key: baseline.source(sha, "src/shared_market_history/" + path)
            for key, path in paths.items()
        }
        for sha in baseline.VERSIONS
    }


def method(raw, name, **globals_):
    node = next(
        n for n in ast.walk(ast.parse(raw)) if isinstance(n, ast.FunctionDef) and n.name == name
    )
    namespace = {"time": time, **globals_}
    body = [
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        node,
    ]
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
            "isolated-extracted-reader:" + name,
            "exec",
        ),
        namespace,
    )
    return namespace[name]


def fail(*args, **kwargs):
    raise RuntimeError("SYNTHETIC_CHECKPOINT_UNREADABLE")


def test_actual_http_boundary_returns_500_not_empty200(readers, actual):
    response = []
    errors = []
    caller = SimpleNamespace(
        path="/v1/metadata/SYNTHETICUSDT",
        headers={},
        api_service=SimpleNamespace(
            get_metadata=fail,
            metrics=SimpleNamespace(
                record_query=lambda *args: None, record_api_error=lambda: errors.append("error")
            ),
        ),
        _send_json=lambda status, payload: response.append((status, payload)),
    )
    do_get = method(
        readers[actual.sha]["server"],
        "do_GET",
        urllib=urllib,
        AsOfViolation=type("FixtureAsOfViolation", (Exception,), {}),
        _symbol_from_path=lambda *args: "SYNTHETICUSDT",
        LOGGER=SimpleNamespace(exception=lambda *args: None),
    )
    do_get(caller)
    assert response == [(500, {"error": "internal_error", "message": "RuntimeError"})]
    assert errors == ["error"]


def test_valid_actual_dict_and_list_shape(actual):
    cp = baseline.checkpoint(actual)
    cp["future_control"] = {"flag": True, "value": 1}
    actual.store.save(cp)
    assert type(baseline.checkpoint(actual)) is dict
    assert type(actual.store.list_all()) is list
    assert actual.store.list_all()[0]["future_control"] == cp["future_control"]


def test_api_strict_corrupt_failure_propagates_not_normal_empty(readers, actual):
    coverage = method(
        readers[actual.sha]["api"],
        "_metadata_coverage",
        RETENTION_DAYS={},
        now_ms=lambda: 0,
        TIMEFRAME_MS={"1d": 86400000},
    )
    caller = SimpleNamespace(checkpoints=SimpleNamespace(load=fail))
    with pytest.raises(RuntimeError, match="CHECKPOINT_UNREADABLE"):
        coverage(caller, "SYNTHETICUSDT", "1d", {"row_count": 1}, {})
    # This tests a FUTURE strict error crossing the current reader, not the old loader.
    caller.checkpoints = actual.store
    assert coverage(caller, "SYNTHETICUSDT", "1d", {"row_count": 1}, {}) == "PARTIAL_HISTORY"


def test_stats_strict_error_and_actual_cached_ok_gap(readers, actual):
    compute = method(readers[actual.sha]["stats"], "_compute_checkpoint_summary")
    caller = SimpleNamespace(
        checkpoints=SimpleNamespace(list_all=fail),
        _snapshot={"generated_at": int(time.time() * 1000), "health": {"service_status": "OK"}},
    )
    with pytest.raises(RuntimeError):
        compute(caller)
    health = method(readers[actual.sha]["stats"], "health")
    assert health(caller)["service_status"] == "OK"  # reproduced stale-success gap, not PASS safety


def test_maintenance_strict_failure_prevents_index_result(readers, actual):
    index = method(readers[actual.sha]["maintenance"], "_checkpoint_index")
    caller = SimpleNamespace(checkpoints=SimpleNamespace(list_all=fail))
    with pytest.raises(RuntimeError):
        index(caller)
    # The pure leaf has no cleanup/ingestion. Full controller loops are not run.
    caller.checkpoints = actual.store
    assert index(caller) == {}


@pytest.mark.parametrize(
    "raw,outcome",
    [
        (b"{broken", "CORRUPT"),
        (b"[]", "SCHEMA_INVALID"),
        (b'{"schema_version":2}', "VERSION_UNSUPPORTED"),
        (
            b'{"dataset":"candles","symbol":"X","completed":false,"retry_count":true}',
            "SCHEMA_INVALID",
        ),
    ],
)
def test_reference_strict_failures_never_fresh_default(raw, outcome):
    assert classify(raw) == "CHECKPOINT_" + outcome
    assert classify(None, io_error=PermissionError()) == "CHECKPOINT_UNREADABLE"
    assert classify(None, io_error=FileNotFoundError()) == "CHECKPOINT_MISSING"


def test_cli_and_external_calls_old_ownership_defect_retained(actual):
    baseline.test_cli_backfill_calls_real_store_without_lease(actual)
    baseline.test_checkpoint_store_bypasses_an_unacquired_lease(actual)


def test_cas_competitor_inside_real_fixture_window_cannot_replace():
    lab = p4.FixtureCAS({"fixture_revision": 1, "fixture_note": "old", "unknown": {"flag": True}})
    try:
        old = lab.path.read_bytes()
        desired = {**p4.decode(old), "fixture_revision": 2, "fixture_note": "new"}
        outcomes = []

        def contender():
            try:
                lab.update(p4.digest(old), desired)
            except BlockingIOError:
                outcomes.append("BLOCKED")

        def during_compare():
            thread = threading.Thread(target=contender)
            thread.start()
            thread.join(timeout=2)
            assert not thread.is_alive()
            assert outcomes == ["BLOCKED"]

        lab.update(p4.digest(old), desired, before_compare=during_compare)
        assert p4.decode(lab.path.read_bytes())["unknown"] == {"flag": True}
    finally:
        lab.close()
    # Uses the EXISTING synthetic revision protocol; NOT proof of no-format CAS.


def test_unknown_fields_and_bool_int_cannot_drift_fixture():
    lab = p4.FixtureCAS({"fixture_revision": 1, "fixture_note": "old", "unknown": {"flag": True}})
    try:
        old = lab.path.read_bytes()
        for changed in ({"flag": 1}, {"flag": True, "extra": 3}):
            desired = {**p4.decode(old), "fixture_revision": 2, "unknown": changed}
            with pytest.raises(ValueError):
                lab.update(p4.digest(old), desired)
            assert lab.path.read_bytes() == old
    finally:
        lab.close()


def test_unknown_commit_stops_fixture_dispatch_but_restart_not_proven():
    lab = p4.FixtureCAS({"fixture_revision": 1, "fixture_note": "old"})
    try:
        old = lab.path.read_bytes()
        desired = {**p4.decode(old), "fixture_revision": 2, "fixture_note": "new"}
        stopped = False
        attempts = 0
        with patch.object(lab, "_sync_dir", side_effect=OSError("unknown outcome")):
            try:
                attempts += 1
                lab.update(p4.digest(old), desired)
            except OSError:
                stopped = True
            if not stopped:
                attempts += 1
                lab.update(p4.digest(old), desired)
        assert stopped and attempts == 1
        assert lab.path.read_bytes() == p4.encode(desired)
        assert (
            admit(
                reader_scope_complete=True,
                historical_schema_proven=False,
                restart_unknown_safe=False,
            )["scope"]
            == "BLOCKED"
        )
    finally:
        lab.close()
    # In-memory stop cannot survive restart; C4 operational admission remains BLOCKED.


def test_no_persistent_identity_no_cross_restart_pass():
    assert (
        admit(
            reader_scope_complete=True, historical_schema_proven=True, restart_unknown_safe=False
        )["scope"]
        == "BLOCKED"
    )


def test_seven_file_scope_and_unknown_inputs_do_not_admit():
    graph = json.loads((ROOT / "docs/P42R_INTERNAL_CALL_EDGES.json").read_text())
    matrix = compatibility_matrix(graph)
    assert matrix == json.loads((ROOT / "docs/P43G1_READER_COMPATIBILITY_MATRIX.json").read_text())
    assert matrix["SEVEN_FILE_SCOPE_SUFFICIENT"] == "NO"
    assert len(matrix["ADDITIONAL_CALLER_FILES_REQUIRED"]) == 2
    for changed in (False, "PASS", 1, None):
        assert (
            admit(
                reader_scope_complete=changed,
                historical_schema_proven=True,
                restart_unknown_safe=True,
            )["scope"]
            == "BLOCKED"
        )
    assert (
        admit(reader_scope_complete=True, historical_schema_proven=True, restart_unknown_safe=True)[
            "implementation"
        ]
        == "NOT_STARTED"
    )
    with pytest.raises(ValueError):
        compatibility_matrix({"versions": []})
    graph["versions"][0]["source_sha"] = "UNKNOWN"
    with pytest.raises(ValueError):
        compatibility_matrix(graph)


def test_checkpoint_fixture_failure_leaves_actual_global_atomic_unchanged(actual):
    helper = actual.modules["storage.atomic"].atomic_write_json
    path = actual.root / "synthetic-generic-json.json"
    helper(path, {"fixture": True})
    assert json.loads(path.read_text()) == {"fixture": True}
    assert actual.modules["storage.atomic"].atomic_write_json is helper
    # Generic JSON helper, NOT actual Parquet serialization or power-loss proof.
