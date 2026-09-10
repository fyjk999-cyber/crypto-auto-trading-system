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



def test_strict_time_order_rejects_future_leakage():
    from crypto_trader.validation.time_split import assert_strict_time_order

    train = [{"ts": 1}, {"ts": 2}]
    val = [{"ts": 3}]
    test = [{"ts": 4}, {"ts": 5}]
    assert_strict_time_order(train, val, test, key=lambda x: x["ts"])
    with pytest.raises(ValueError):
        assert_strict_time_order(
            train, val, [{"ts": 1}], key=lambda x: x["ts"]
        )


def test_strict_time_order_rejects_non_monotonic_within_split():
    from crypto_trader.validation.time_split import assert_strict_time_order

    with pytest.raises(ValueError):
        assert_strict_time_order(
            [{"ts": 2}, {"ts": 1}],
            [{"ts": 3}],
            [{"ts": 4}],
            key=lambda x: x["ts"],
        )


def test_label_must_be_future_of_feature():
    from crypto_trader.validation.time_split import assert_label_is_future

    assert_label_is_future(1, 2)
    with pytest.raises(ValueError):
        assert_label_is_future(2, 1)


def test_embargo_gap_rejects_adjacent_windows():
    from crypto_trader.validation.time_split import assert_embargo_gap

    assert_embargo_gap([{"ts": 1}], [{"ts": 3}], key=lambda x: x["ts"])
    with pytest.raises(ValueError):
        assert_embargo_gap([{"ts": 1}], [{"ts": 2}], key=lambda x: x["ts"])


def test_test_observations_cannot_be_used_for_tuning():
    from crypto_trader.validation.time_split import assert_test_not_used_for_tuning

    assert_test_not_used_for_tuning({1, 2}, {3, 4})
    with pytest.raises(ValueError):
        assert_test_not_used_for_tuning({1, 2}, {2, 3})
