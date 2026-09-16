import json
from pathlib import Path


async def test_growth_status_is_read_only_and_truthful(database, tmp_path):
    (tmp_path / "growth_heartbeat.json").write_text(
        json.dumps(
            {
                "state": "ACCUMULATING",
                "pid": 11,
                "runtime_sha": "sha-x",
                "stage": "CYCLE_COMPLETE",
                "cycles_started": 2,
                "cycles_completed": 2,
                "effective_scan_batch": 500,
                "effective_outcome_batch": 25,
                "effective_memory_batch": 200,
                "effective_review_batch": 100,
            }
        )
    )
    (tmp_path / "growth_state.json").write_text(json.dumps({"metrics": {}}))
    from crypto_trader.growth_status import growth_status

    status = await growth_status(database.session_factory, tmp_path)
    assert status["authority"] == "LEARNING_ONLY"
    assert status["is_order"] is False and status["can_modify_core"] is False
    assert status["service"]["state"] == "ACCUMULATING"
    assert status["configuration"]["outcome_batch"] == 25
    assert status["ledger"]["rows"] == 0
    assert status["llm_advisory"] == "DISABLED_PENDING_CANONICAL_FLASH_MERGE"


def test_growth_status_route_is_read_only():
    source = (Path(__file__).resolve().parents[2] / "src/crypto_trader/api/app.py").read_text()
    assert '@app.get("/growth/status")' in source
    assert '@app.post("/growth/status")' not in source
