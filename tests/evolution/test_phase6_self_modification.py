from crypto_trader.evolution.foundation.policy import EvolutionMutationPolicy
from crypto_trader.evolution.validation.certification import certify
from crypto_trader.evolution.validation.materializer import CandidateMaterializer
from crypto_trader.evolution.validation.pipeline import ValidationPipeline
from crypto_trader.evolution.validation.workspace import CandidateWorkspaceManager


def make_manager():
    return CandidateWorkspaceManager(policy=EvolutionMutationPolicy())


def test_protected_core_path_blocked_and_quarantined():
    manager = make_manager()
    ws = manager.create(candidate_id="c1", parent_commit="abc", parent_version="v1",
                        allowed_paths=["src/crypto_trader/factors/"])
    ok, reason = manager.record_write(ws, "src/crypto_trader/runtime/engine.py")
    assert ok is False
    assert reason == "PROTECTED_PATH"
    assert ws.workspace_status == "QUARANTINED"


def test_path_escape_blocked():
    manager = make_manager()
    ws = manager.create(candidate_id="c2", parent_commit="abc", parent_version="v1",
                        allowed_paths=["src/crypto_trader/factors/"])
    ok, reason = manager.record_write(ws, "../../etc/passwd")
    assert ok is False
    assert reason in ("PATH_ESCAPE", "ABSOLUTE_PATH_ESCAPE", "PATH_NOT_ALLOWED")


def test_allowed_write_and_diff_budget():
    manager = make_manager()
    ws = manager.create(candidate_id="c3", parent_commit="abc", parent_version="v1",
                        allowed_paths=["src/crypto_trader/factors/"])
    ok, _ = manager.record_write(ws, "src/crypto_trader/factors/weights.json",
                                 loc_added=5)
    assert ok is True
    assert "src/crypto_trader/factors/weights.json" in ws.changed_files


def test_materializer_quarantines_on_protected_edit():
    manager = make_manager()
    manager.create(candidate_id="c4", parent_commit="abc", parent_version="v1",
                   allowed_paths=["src/crypto_trader/factors/"])
    materializer = CandidateMaterializer(manager)
    result = materializer.apply("c4", [
        {"path": "src/crypto_trader/risk/engine.py", "loc_added": 1}],
        candidate_commit="c4", diff_hash="h")
    assert result.status == "QUARANTINED"


def test_materializer_success():
    manager = make_manager()
    manager.create(candidate_id="c5", parent_commit="abc", parent_version="v1",
                   allowed_paths=["src/crypto_trader/factors/"])
    materializer = CandidateMaterializer(manager)
    result = materializer.apply("c5", [
        {"path": "src/crypto_trader/factors/weights.json", "loc_added": 2}],
        candidate_commit="c5", diff_hash="h5")
    assert result.status == "MATERIALIZED"
    assert result.diff_hash == "h5"


def test_validation_pipeline_all_gates_pass():
    run = ValidationPipeline().run(
        run_id="r1", candidate_id="c1",
        gate_results=[
            {"gate": "PROTECTED_PATH_CHECK", "passed": True},
            {"gate": "STATIC_ANALYSIS", "passed": True},
            {"gate": "UNIT_TEST", "passed": True},
        ],
        champion_metrics={"sharpe": 1.0}, challenger_metrics={"sharpe": 1.2},
        success_metrics={"sharpe": "improve"}, guardrail_metrics={})
    assert run.status == "VALIDATED"
    assert certify(run).status == "PASS"


def test_validation_pipeline_rejects_failure():
    run = ValidationPipeline().run(
        run_id="r2", candidate_id="c2",
        gate_results=[{"gate": "STATIC_ANALYSIS", "passed": False, "reason": "lint"}],
        champion_metrics={}, challenger_metrics={}, success_metrics={},
        guardrail_metrics={})
    assert run.status == "REJECTED"
    assert certify(run).status == "FAIL"


def test_validation_pipeline_guardrail_blocks_good_return():
    run = ValidationPipeline().run(
        run_id="r3", candidate_id="c3",
        gate_results=[{"gate": "UNIT_TEST", "passed": True}],
        champion_metrics={"return": 0.1}, challenger_metrics={"return": 0.3},
        success_metrics={"return": "improve"},
        guardrail_metrics={"max_drawdown": {"passed": False, "reason": "DD breach"}})
    assert run.status == "REJECTED"
    assert certify(run).status == "QUARANTINE"
