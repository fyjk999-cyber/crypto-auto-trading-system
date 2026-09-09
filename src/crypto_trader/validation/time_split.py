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
