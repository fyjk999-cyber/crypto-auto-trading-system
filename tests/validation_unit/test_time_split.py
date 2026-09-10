import pytest

from crypto_trader.validation.time_split import split_ordered


def test_split_preserves_time_order_and_partitions():
    items = list(range(10))
    train, val, test = split_ordered(items, train=0.6, val=0.2)
    assert train == [0, 1, 2, 3, 4, 5]
    assert val == [6, 7]
    assert test == [8, 9]


def test_split_rejects_leaky_or_empty_test():
    with pytest.raises(ValueError):
        split_ordered([1, 2], train=0.6, val=0.2)
    with pytest.raises(ValueError):
        split_ordered(list(range(5)), train=0.8, val=0.3)



def test_split_allows_no_validation_window():
    train, val, test = split_ordered(list(range(10)), train=0.5, val=0.0)
    assert val == []
    assert test == [5, 6, 7, 8, 9]



def test_split_rejects_non_positive_train_fraction():
    with pytest.raises(ValueError):
        split_ordered(list(range(10)), train=0.0, val=0.2)


def test_split_rejects_empty_items():
    with pytest.raises(ValueError):
        split_ordered([], train=0.5, val=0.2)

