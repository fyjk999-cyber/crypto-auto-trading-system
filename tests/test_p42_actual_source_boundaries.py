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


def test_permission_failure_is_not_missing(actual):
    checkpoint(actual)
    with patch.object(
        actual.modules["storage.checkpoint_store"],
        "read_json",
        side_effect=PermissionError("fixture denial"),
    ):
        with pytest.raises(PermissionError):
            checkpoint(actual)


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
