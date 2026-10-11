import json

import pytest

from scripts.p42_load_reference import classify


def document(**changes):
    value = dict(
        dataset="candles",
        symbol="SYNTHETICUSDT",
        completed=True,
        retry_count=0,
        future_control={"nested": [True, 1]},
        restored_reason="FIXTURE_ONLY",
    )
    value.update(changes)
    return json.dumps(value).encode()


@pytest.mark.parametrize(
    "raw,error,expected",
    [
        (b"", FileNotFoundError(), "CHECKPOINT_MISSING"),
        (b"", PermissionError(), "CHECKPOINT_UNREADABLE"),
        (b"{broken", None, "CHECKPOINT_CORRUPT"),
        (b'{"x":1,"x":2}', None, "CHECKPOINT_CORRUPT"),
        (b'{"x":NaN}', None, "CHECKPOINT_CORRUPT"),
        (b"\xff", None, "CHECKPOINT_CORRUPT"),
        (b"[]", None, "CHECKPOINT_SCHEMA_INVALID"),
        (document(schema_version=2), None, "CHECKPOINT_VERSION_UNSUPPORTED"),
        (document(schema_version=True), None, "CHECKPOINT_SCHEMA_INVALID"),
        (document(completed=1), None, "CHECKPOINT_SCHEMA_INVALID"),
        (document(retry_count=True), None, "CHECKPOINT_SCHEMA_INVALID"),
        (document(), None, "CHECKPOINT_VALID"),
    ],
)
def test_reference_classification(raw, error, expected):
    assert classify(raw, io_error=error) == expected


def test_reference_never_rewrites_unknown_or_historical_bytes():
    raw = document()
    before = raw
    assert classify(raw) == "CHECKPOINT_VALID"
    assert raw == before
    assert json.loads(raw)["future_control"] == {"nested": [True, 1]}


@pytest.mark.parametrize("number", ["1e999", "-1e999"])
def test_nested_number_overflow_is_corrupt(number):
    raw = document().decode().removesuffix("}") + ', "unknown": {"nested": [' + number + "]}}"
    assert classify(raw.encode()) == "CHECKPOINT_CORRUPT"
