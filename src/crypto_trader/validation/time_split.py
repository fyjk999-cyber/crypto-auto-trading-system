"""Deterministic time-ordered train/validation/test split (no shuffle/leakage)."""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def split_ordered(
    items: list[T], *, train: float = 0.6, val: float = 0.2
) -> tuple[list[T], list[T], list[T]]:
    if not 0.0 < train < 1.0 or not 0.0 <= val < 1.0 or train + val >= 1.0:
        raise ValueError("train/val fractions must produce a non-empty test window")
    n = len(items)
    if n < 3:
        raise ValueError("at least 3 items required")
    train_n = max(1, int(n * train))
    val_n = max(1, int(n * val)) if val > 0 else 0
    # Guarantee a test window remains.
    if train_n + val_n >= n:
        train_n = max(1, n - val_n - 1)
    train_items = items[:train_n]
    val_items = items[train_n : train_n + val_n]
    test_items = items[train_n + val_n :]
    if not test_items:
        raise ValueError("time split left no test items")
    return train_items, val_items, test_items


def assert_strict_time_order(
    train: list, val: list, test: list, *, key
) -> None:
    """Reject future leakage or non-monotonic time splits."""
    if not train or not test:
        raise ValueError("train and test must be non-empty")
    train_keys = [key(item) for item in train]
    val_keys = [key(item) for item in val]
    test_keys = [key(item) for item in test]
    for keys in (train_keys, val_keys, test_keys):
        if any(a >= b for a, b in zip(keys, keys[1:], strict=False)):
            raise ValueError("timestamps must be strictly increasing")
    if val_keys and train_keys[-1] >= val_keys[0]:
        raise ValueError("train/test overlap")
    if val_keys and val_keys[-1] >= test_keys[0]:
        raise ValueError("validation/test overlap")
    if train_keys[-1] >= test_keys[0]:
        raise ValueError("train/test overlap")


def assert_label_is_future(feature_ts, label_ts) -> None:
    """Reject future-label leakage in supervised validation data."""
    if label_ts <= feature_ts:
        raise ValueError("label timestamp must be after feature timestamp")


def assert_embargo_gap(
    train: list, test: list, *, key, min_gap: int = 1
) -> None:
    """Reject adjacent train/test windows without a purge/embargo gap."""
    if not train or not test:
        raise ValueError("train and test must be non-empty")
    if key(test[0]) - key(train[-1]) <= min_gap:
        raise ValueError("train/test embargo gap too small")


def assert_test_not_used_for_tuning(
    test_indices: set[int], tuned_indices: set[int]
) -> None:
    """Reject parameter selection that touched final test observations."""
    if test_indices & tuned_indices:
        raise ValueError("test observations used for parameter tuning")
