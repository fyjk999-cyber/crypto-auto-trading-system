from crypto_trader.ml_shadow import ShadowStore, decide_promotion, post_cost_validation


def _metrics(net, auc=0.7, folds=3):
    return {"walk_forward": {"fold_count": folds, "auc": auc, "mean_net_bps_valid": net}}


def test_post_cost_requires_positive_net_edge():
    bad = post_cost_validation(_metrics(-5.0))
    assert bad["passed"] is False
    assert any("net_edge_not_positive" in r for r in bad["reasons"])
    good = post_cost_validation(_metrics(12.0))
    assert good["passed"] is True and good["reasons"] == []
    low_auc = post_cost_validation(_metrics(12.0, auc=0.51))
    assert low_auc["passed"] is False


def test_shadow_store_persists_and_evaluates_without_authority(tmp_path):
    store = ShadowStore(tmp_path / "shadow.jsonl")
    row = store.record(
        model_id="21_ORDER_FLOW_ML",
        model_version="v1-abc",
        symbol="BTCUSDT",
        probability=0.7,
        expected_edge=25.0,
        confidence=0.6,
    )
    assert row["authority"] == "LEARNING_ONLY" and row["is_order"] is False
    assert store.attach_outcome(row["prediction_id"], 18.0) is True
    assert store.attach_outcome("missing", 1.0) is False
    summary = store.summary("21_ORDER_FLOW_ML", "v1-abc")
    assert summary == {"samples": 1, "mean_net_bps": 18.0, "win_rate": 1.0}


def test_promotion_gate_is_deterministic():
    assert (
        decide_promotion(
            post_cost_passed=True,
            fold_count=3,
            shadow_summary={"samples": 5, "mean_net_bps": 10.0, "win_rate": 0.8},
            min_shadow=30,
        )
        == "CONTINUE_SHADOW"
    )
    assert (
        decide_promotion(
            post_cost_passed=True,
            fold_count=3,
            shadow_summary={"samples": 30, "mean_net_bps": 10.0, "win_rate": 0.6},
            min_shadow=30,
        )
        == "PROMOTE"
    )
    assert (
        decide_promotion(
            post_cost_passed=True,
            fold_count=3,
            shadow_summary={"samples": 30, "mean_net_bps": -2.0, "win_rate": 0.6},
            min_shadow=30,
        )
        == "REJECT"
    )
    assert (
        decide_promotion(
            post_cost_passed=False,
            fold_count=3,
            shadow_summary={"samples": 30, "mean_net_bps": 10.0, "win_rate": 0.6},
            min_shadow=30,
        )
        == "REJECT"
    )
