from crypto_trader.ml_registry import ModelRegistry


def _reg(tmp_path):
    return ModelRegistry(tmp_path / "registry.json")


def test_register_is_immutable_and_versions_are_distinct(tmp_path):
    r = _reg(tmp_path)
    a = r.register(
        model_id="21_ORDER_FLOW_ML", model_version="v1", artifact_path="x", artifact_hash="h1"
    )
    same = r.register(
        model_id="21_ORDER_FLOW_ML", model_version="v1", artifact_path="y", artifact_hash="h2"
    )
    assert same["artifact_hash"] == "h1"
    b = r.register(
        model_id="21_ORDER_FLOW_ML", model_version="v2", artifact_path="z", artifact_hash="h2"
    )
    assert a["model_version"] != b["model_version"] and len(r.data["models"]) == 2


def test_active_supersedes_previous_and_rollback(tmp_path):
    r = _reg(tmp_path)
    r.register(model_id="m", model_version="v1", artifact_path="a", artifact_hash="h1")
    r.set_state("m", "v1", "ACTIVE")
    assert r.active_version("m") == "v1"
    r.register(model_id="m", model_version="v2", artifact_path="b", artifact_hash="h2")
    r.set_state("m", "v2", "ACTIVE")
    assert r.active_version("m") == "v2"
    assert r.get("m", "v1")["state"] == "SUPERSEDED"
    r.set_state("m", "v2", "DEGRADED", reason="degraded")
    assert r.active_version("m") is None
    assert r.get("m", "v2")["state"] == "DEGRADED"
    assert r.get("m", "v2")["history"][-1]["reason"] == "degraded"


def test_invalid_state_rejected(tmp_path):
    r = _reg(tmp_path)
    try:
        r.register(
            model_id="m", model_version="v1", artifact_path="a", artifact_hash="h", state="NOPE"
        )
    except ValueError as exc:
        assert "invalid_state" in str(exc)
    else:
        raise AssertionError("invalid state must fail")
