"""Pinned source index reproducibility; never treats enumeration as callgraph PASS."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "/Users/huhongjie/Documents/ChatGPT/shared-market-history"


def test_source_inventory_reproducible_from_exact_git_objects():
    result = subprocess.check_output(
        [sys.executable, str(ROOT / "scripts/p41_source_inventory.py"), REPO]
    )
    assert json.loads(result) == json.loads((ROOT / "docs/P41_SOURCE_INVENTORY.json").read_text())


def test_enumeration_does_not_claim_external_or_dynamic_closure():
    inventory = json.loads((ROOT / "docs/P41_SOURCE_INVENTORY.json").read_text())
    for version in inventory["versions"]:
        assert version["full_callgraph"] == "NOT_PROVEN"
        assert version["metadata_exclusion_allowlist"] == []
        assert len(version["unreviewed_tracked_source_names"]) == 22
        assert version["unreviewed_tracked_source_classification"] == (
            "UNRESOLVED_DYNAMIC_SCOPE_NOT_ESTABLISHED"
        )


def test_full_field_set_and_historical_origin_are_not_fabricated():
    catalog = json.loads((ROOT / "docs/P41_FIELD_CATALOG.json").read_text())
    assert catalog["field_set_completeness"].startswith("BLOCKED_")
    assert catalog["t0_projection"]["equality"] == "NOT_PROVABLE"
    assert catalog["metadata_exclusion_allowlist"] == []
    for version in catalog["versions"]:
        assert len(version["fields"]) == 20
        for field in version["fields"]:
            if field["FIELD_NAME"].startswith("restored_"):
                assert field["VERSION_INTRODUCED"] == "NOT_RECOVERED"
                assert field["VERDICT"] == "ORPHANED_BUT_PROTECTED"


def test_entry_matrix_retains_defects_unknown_lease_and_scope():
    matrix = json.loads((ROOT / "docs/P41_ENTRYPOINT_MATRIX.json").read_text())
    assert matrix["full_callgraph"] == "BLOCKED"
    for version in matrix["versions"]:
        assert len(version["entries"]) == 15
        cli = next(row for row in version["entries"] if row["ENTRYPOINT"].startswith("CLI"))
        assert cli["LEASE_BOUNDARY"] == "LEASE_NOT_ACQUIRED"
        assert cli["CLASSIFICATION"] == "PROVEN_DEFECT"
        assert any(row["CLASSIFICATION"] == "UNRESOLVED_DYNAMIC" for row in version["entries"])
