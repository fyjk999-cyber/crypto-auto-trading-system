"""Additional defect reproductions, not safety approval or production repair."""

import os
from unittest.mock import patch

import pytest

from tests.test_p41_real_checkpoint_source import actual as actual
from tests.test_p41_real_checkpoint_source import checkpoint


def test_unknown_nested_field_lost_in_write_window(actual):
    cp = checkpoint(actual)
    actual.store.save(cp)
    path = actual.store.path_for("candles", "SYNTHETICUSDT", "1d")
    atomic = actual.modules["storage.atomic"]
    replace = atomic.os.replace

    def competing_write(src, dst):
        with patch.object(atomic.os, "replace", replace):
            current = checkpoint(actual)
            current["future_control"] = {"nested": [True, 1]}
            actual.store.save(current)
        return replace(src, dst)

    with patch.object(atomic.os, "replace", competing_write):
        actual.store.save(cp)
    assert "future_control" not in checkpoint(actual)
    assert path.is_file()


def test_success_bool_coercion_changes_control_semantics(actual):
    actual.store.mark_success("candles", "SYNTHETICUSDT", "1d", completed="false")
    assert checkpoint(actual)["completed"] is True


def test_actual_unreadable_document_looks_missing(actual):
    cp = checkpoint(actual)
    cp["completed"] = True
    actual.store.save(cp)
    path = actual.store.path_for("candles", "SYNTHETICUSDT", "1d")
    before = path.read_bytes()
    # Inject at the file-open boundary, leaving actual read_json handling intact.
    with patch.object(type(path), "open", side_effect=PermissionError("fixture denial")):
        result = checkpoint(actual)
    assert result["completed"] is False
    assert result["status"] == "NOT_STARTED"
    assert path.read_bytes() == before


def test_post_publish_overwrite_not_detected(actual):
    cp = checkpoint(actual)
    cp["completed"] = True
    atomic = actual.modules["storage.atomic"]
    original = atomic.fsync_dir

    def overwrite_after_publish(directory):
        with patch.object(atomic, "fsync_dir", original):
            current = checkpoint(actual)
            current["completed"] = False
            actual.store.save(current)
        original(directory)

    with patch.object(atomic, "fsync_dir", overwrite_after_publish):
        returned = actual.store.save(cp)
    assert returned["completed"] is True
    assert checkpoint(actual)["completed"] is False


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires isolated POSIX child")
def test_different_process_store_bypasses_active_lease(actual):
    lease = actual.modules["storage.writer_lease"].WriterLease(actual.settings)
    assert lease.acquire()
    checkpoint(actual)
    child = os.fork()
    if child == 0:
        try:
            other = type(actual.store)(actual.settings)
            cp = other.load("candles", "SYNTHETICUSDT", "1d")
            cp["next_cursor"] = 314
            other.save(cp)
        except BaseException:
            os._exit(1)
        os._exit(0)
    try:
        _, status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        assert checkpoint(actual)["next_cursor"] == 314
    finally:
        lease.release()
