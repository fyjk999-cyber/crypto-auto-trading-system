import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "evidence-v2/verification"))
sys.path.insert(0, str(ROOT / "scripts"))
import p3  # noqa: E402
import publish_static_kb as kb  # noqa: E402
import s2_contracts as s2  # noqa: E402


def manifest():
    blobs = {"receipt": b"new phase", "test": b"fixture", "source": b"pinned source"}
    return p3.forward_manifest(1, None, "a" * 40, blobs, "2026-10-11T00:00:00Z"), blobs


def test_legacy_failure_retained_with_valid_forward_chain():
    m, blobs = manifest()
    result = p3.verify_forward(m, blobs, p3.sha(p3.encode(m)))
    assert result["FORWARD_EVIDENCE_CHAIN"] == "PASS_LOCAL_CONTENT_ONLY"
    assert result["LEGACY_EVIDENCE"] == "FAIL_MISMATCH"
    assert result["INDEPENDENT_CUSTODY"] == "NOT_ESTABLISHED"
    assert s2.legacy_citation(b"current", "69a087f50c320221")["citation"] == "MISMATCH"
    assert s2.full_verdict({"SAFE_INVENTORY": "PASS", "FACTUAL_DATA_VERIFICATION": "BLOCKED",
                            "IMMUTABLE_LEDGER_VALIDATION": "FAIL"}) == "BLOCKED"


@pytest.mark.parametrize("fault", ["receipt", "missing", "scope", "version", "parent"])
def test_forward_negative(fault):
    m, blobs = manifest()
    pin = p3.sha(p3.encode(m))
    if fault == "receipt":
        blobs["receipt"] = b"changed"
    elif fault == "missing":
        del blobs["test"]
    elif fault == "scope":
        m["scope"] = "RETROACTIVE_T0"
        pin = p3.sha(p3.encode(m))
    else:
        parent = dict(m)
        m = p3.forward_manifest(2, p3.sha(p3.encode(parent)), "b" * 40, blobs,
                                "2026-10-11T01:00:00Z")
        if fault == "version":
            m["version"] = 3
        else:
            m["parent_sha256"] = "0" * 64
        with pytest.raises(ValueError):
            p3.verify_forward(m, blobs, p3.sha(p3.encode(m)), parent)
        return
    with pytest.raises(ValueError):
        p3.verify_forward(m, blobs, pin)


def test_same_uid_rewrite_and_mutable_state_cannot_grant_custody():
    m, blobs = manifest()
    original = p3.encode(m)
    state = {"pointer": "next"}
    state["pointer"] = "later"
    assert p3.encode(m) == original
    blobs["receipt"] = b"rewrite by same UID"
    rewritten = p3.forward_manifest(1, None, "c" * 40, blobs, "2026-10-11T02:00:00Z")
    assert p3.verify_forward(rewritten, blobs, p3.sha(p3.encode(rewritten)))[
        "INDEPENDENT_CUSTODY"] == "NOT_ESTABLISHED"


def test_inventory_refuses_content_and_lock(tmp_path):
    path = tmp_path / "db"
    path.write_bytes(b"fixture only")
    reader = s2.SafeInventoryReader([path])
    assert reader.metadata(path)["content_integrity"] == "NOT_VERIFIED"
    for mode in ("rb", "r+"):
        with pytest.raises(PermissionError):
            reader.open_content(path, mode)
    with pytest.raises(PermissionError):
        reader.acquire_lock(path)


def test_read_contract_is_not_production_admission():
    contract = dict.fromkeys(p3.DATA_READ_REQUIREMENTS, "fixture-only-known")
    contract.update(max_bytes=100, max_memory_bytes=100, max_seconds=1)
    assert p3.data_read_contract(contract) == "BLOCKED_UNTIL_PRODUCTION_ADMISSION"
    del contract["wal_consistency"]
    with pytest.raises(ValueError):
        p3.data_read_contract(contract)
    data = b"fixture" * 1000
    start = time.perf_counter()
    assert p3.check_fixture_bytes(data, p3.sha(data), 7000)["fixture_integrity"] == "PASS"
    assert time.perf_counter() - start < 1
    with pytest.raises(ValueError):
        p3.check_fixture_bytes(data, p3.sha(data), 10)
    with pytest.raises(ValueError):
        p3.check_fixture_bytes(data, "0" * 64, 7000)


def candidate(tmp_path):
    source = ROOT / "docs/research/knowledge-candidates" / kb.SOURCE_SHA
    dest = tmp_path / "docs/research/knowledge-candidates" / kb.SOURCE_SHA
    shutil.copytree(source, dest)
    return dest


def test_static_publish_repeat_and_no_overwrite(tmp_path):
    candidate(tmp_path)
    target = kb.publish(tmp_path)
    assert kb.publish(tmp_path) == target
    path = target / "lowrisk/MODEL_KB.md"
    path.write_bytes(b"user change")
    with pytest.raises(ValueError):
        kb.publish(tmp_path)
    assert path.read_bytes() == b"user change"


def test_static_corruption_or_symlink_never_publishes(tmp_path):
    source = candidate(tmp_path)
    doc = source / "docs/research/standby/lowrisk/MODEL_KB.md"
    doc.write_bytes(b"corruption")
    with pytest.raises(ValueError):
        kb.publish(tmp_path)
    assert not (tmp_path / "docs/research/knowledge-library/v2" / kb.SOURCE_SHA).exists()
    doc.unlink()
    doc.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError):
        kb.publish(tmp_path)


def test_static_failure_keeps_staging_not_active(tmp_path, monkeypatch):
    candidate(tmp_path)
    real = Path.write_bytes

    def fail(path, data):
        if ".static-stage-" in str(path) and path.name == "MODEL_KB.md":
            raise OSError("injected fixture disk failure")
        return real(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail)
    with pytest.raises(OSError):
        kb.publish(tmp_path)
    assert not (tmp_path / "docs/research/knowledge-library/v2" / kb.SOURCE_SHA).exists()


def test_interface_default_disabled_missing_not_zero_and_no_write_fields():
    with pytest.raises(PermissionError):
        p3.comparison_record({})
    result = p3.comparison_record({}, enabled=True)
    assert result["facts"]["fill_id"] == {
        "status": "NOT_AVAILABLE", "value": None, "source": None}
    assert result["trading_authority"] == "NONE"
    assert result["quant_core_connected"] is False
    for bad in ({"place_order": {}}, {"fill_id": {"value": "", "source": "fixture"}},
                {"gross_pnl": {"value": 0, "source": "fixture"}}):
        with pytest.raises(ValueError):
            p3.comparison_record(bad, enabled=True)


def test_interface_signed_funding_and_accounting_parity():
    facts = {k: {"value": v, "source": "fixture episode only"} for k, v in
             {"gross_pnl": "10", "fees": "2", "funding": "-1", "net_pnl": "7"}.items()}
    assert p3.comparison_record(facts, enabled=True)["facts"]["net_pnl"]["value"] == "7"
    facts["net_pnl"]["value"] = "9"
    with pytest.raises(ValueError):
        p3.comparison_record(facts, enabled=True)


def test_interface_hash_time_provenance_negative():
    for field, value in (("market_asof_utc", "2026-10-11"),
                         ("strategy_package_hash", "unknown"), ("fees", "NaN")):
        with pytest.raises(ValueError):
            p3.comparison_record({field: {"value": value, "source": "fixture"}}, enabled=True)
    with pytest.raises(ValueError):
        p3.comparison_record({"decision_id": {"value": "fixture1", "source": ""}}, enabled=True)


def test_fake_sqlite_wal_consistent_backup_only_in_fixture(tmp_path):
    import sqlite3

    source = tmp_path / "fake.db"
    writer = sqlite3.connect(source)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE fake_facts (value INTEGER)")
    writer.execute("INSERT INTO fake_facts VALUES (1)")
    writer.commit()
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as reader:
        reader.execute("PRAGMA query_only=ON")
        with sqlite3.connect(tmp_path / "fake-snapshot.db") as snapshot:
            reader.backup(snapshot, pages=4)
            assert snapshot.execute("SELECT value FROM fake_facts").fetchall() == [(1,)]
    assert writer.execute("SELECT value FROM fake_facts").fetchall() == [(1,)]
    writer.close()


def test_fixture_resource_measurement_and_control_key_negatives():
    import tracemalloc

    tracemalloc.start()
    start = time.perf_counter()
    data = b"x" * (8 * 1024 * 1024)
    p3.check_fixture_bytes(data, p3.sha(data), len(data))
    seconds = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print({"fixture_bytes": len(data), "seconds": seconds, "peak_tracemalloc_bytes": peak,
           "production_admission": "BLOCKED"})
    assert seconds < 5 and peak < 20 * 1024 * 1024
    original = {"status": "IN_PROGRESS", "completed": True, "pause_reason": "stop requested"}
    for key in ("unknown", "pause_reason", "restored_reason", "forward_bridge_start_ms",
                "newest_fetched", "status", "forward_cursor", "completed", "lease"):
        changed = {**original, key: "changed"}
        assert p3.encode(original) != p3.encode(changed)
