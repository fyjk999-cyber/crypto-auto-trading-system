from crypto_trader.domain.identifiers import is_valid_id, new_id


def test_new_id_has_prefix_and_is_unique():
    a = new_id("ord")
    b = new_id("ord")
    assert a.startswith("ord_")
    assert a != b
    assert is_valid_id(a, "ord")
    assert not is_valid_id(a, "fill")
