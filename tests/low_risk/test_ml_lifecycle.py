from crypto_trader.ml_lifecycle import mark_degraded, rollback, should_retrain
from crypto_trader.ml_registry import ModelRegistry


def test_retrain_requires_data_and_cooldown():
    assert should_retrain(new_samples=0, seconds_since_last_train=10**9)["retrain"] is False
    cooling = should_retrain(new_samples=100, seconds_since_last_train=60)
    assert cooling["retrain"] is False and "cooldown_active" in cooling["reasons"]
    ready = should_retrain(new_samples=100, seconds_since_last_train=10**9)
    assert ready["retrain"] is True
    assert (
        should_retrain(new_samples=0, seconds_since_last_train=0, feature_version_changed=True)[
            "retrain"
        ]
        is True
    )
    degraded = should_retrain(new_samples=0, seconds_since_last_train=0, performance_drop_bps=25.0)
    assert degraded["retrain"] is True


def test_degradation_and_rollback_semantics(tmp_path):
    reg = ModelRegistry(tmp_path / "registry.json")
    reg.register(
        model_id="21_ORDER_FLOW_ML", model_version="v1", artifact_path="a", artifact_hash="h1"
    )
    reg.set_state("21_ORDER_FLOW_ML", "v1", "ACTIVE")
    reg.register(
        model_id="21_ORDER_FLOW_ML", model_version="v2", artifact_path="b", artifact_hash="h2"
    )
    reg.set_state("21_ORDER_FLOW_ML", "v2", "ACTIVE")
    assert reg.get("21_ORDER_FLOW_ML", "v1")["state"] == "SUPERSEDED"
    assert reg.active_version("21_ORDER_FLOW_ML") == "v2"
    mark_degraded(reg, "21_ORDER_FLOW_ML", "v2", reason="drift", degradation_bps=18.0)
    assert reg.get("21_ORDER_FLOW_ML", "v2")["state"] == "DEGRADED"
    assert reg.active_version("21_ORDER_FLOW_ML") is None
    restored = rollback(reg, "21_ORDER_FLOW_ML", reason="degradation")
    assert restored is not None and restored["model_version"] == "v1"
    assert reg.active_version("21_ORDER_FLOW_ML") == "v1"
    assert reg.get("21_ORDER_FLOW_ML", "v2")["state"] == "ROLLED_BACK"
