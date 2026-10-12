"""Old-source route reproductions; passing means defects observed, not repaired."""

import ast
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests import test_p41_real_checkpoint_source as baseline
from tests import test_p42_actual_source_boundaries as boundaries
from tests.test_p41_real_checkpoint_source import actual as actual


@pytest.mark.parametrize("reproduction", [
    baseline.test_cli_backfill_calls_real_store_without_lease,
    baseline.test_checkpoint_store_bypasses_an_unacquired_lease,
    baseline.test_two_stores_allow_stale_overwrite_without_cas,
    baseline.test_post_rename_fsync_failure_has_committed_bytes,
    boundaries.test_unknown_nested_field_lost_in_write_window,
    baseline.test_unknown_and_historical_fields_preserved_on_success,
    baseline.test_retry_mark_error_is_not_idempotent,
])
def test_old_source_route_reproduction(actual, reproduction):
    reproduction(actual)


@pytest.fixture(scope="session")
def engine_sources():
    # Fetch immutable Git bytes before the function-scoped fixture I/O guard.
    return {
        sha: baseline.source(sha, "src/shared_market_history/backfill/engine.py")
        for sha in baseline.VERSIONS
    }


def test_actual_run_task_handler_resaves_after_uncertain_publish(engine_sources, actual):
    source = engine_sources[actual.sha]
    tree = ast.parse(source)
    engine = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BackfillEngine"
    )
    methods = [
        n for n in engine.body if isinstance(n, ast.FunctionDef)
        and n.name in {"run_task", "_timed_ckpt", "_stamp_timing"}
    ]
    namespace = {"time": time, "BackfillResult": actual.modules["backfill.models"].BackfillResult}
    body = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    body.extend(methods)
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
                 actual.sha + ":actual_engine_handler", "exec"), namespace)

    cp = baseline.checkpoint(actual)
    cp.update(completed=True, status="COMPLETE")
    actual.store.save(cp)
    fake_type = type("IsolatedHandlerBoundary", (), {
        name: namespace[name] for name in ("run_task", "_timed_ckpt", "_stamp_timing")
    })
    caller = fake_type()
    caller.checkpoints = actual.store
    caller._slot_tls = SimpleNamespace()
    caller._tls_add = lambda *args: None

    def fixture_worker(*args):
        changed = baseline.checkpoint(actual)
        changed["newest_fetched"] = 123
        actual.store.save(changed)

    caller._run_candle_forward = fixture_worker
    atomic = actual.modules["storage.atomic"]
    original_sync = atomic.fsync_dir
    calls = 0

    def one_postreplace_failure(path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("fixture postreplace uncertainty")
        return original_sync(path)

    task = SimpleNamespace(dataset="candles", symbol="SYNTHETICUSDT",
                           timeframe="1d", task_id="fixture")
    with patch.object(atomic, "fsync_dir", one_postreplace_failure):
        result = caller.run_task(task)
    observed = baseline.checkpoint(actual)
    assert result.status == "ERROR"
    assert observed["completed"] is True and observed["status"] == "ERROR"
    assert observed["newest_fetched"] == 123 and observed["retry_count"] == 1
    assert calls == 2
