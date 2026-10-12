"""Validate actual source-evidence artifacts, never runtime data."""

import copy
import json
from pathlib import Path

import pytest

from scripts.p41_source_inventory import VERSIONS

ROOT = Path(__file__).resolve().parents[1] / "docs"


def validate(edges, matrix):
    for document in (edges, matrix):
        assert [v["source_sha"] for v in document["versions"]] == list(VERSIONS)
    versions = {v["source_sha"]: v for v in edges["versions"]}
    for version in matrix["versions"]:
        sha = version["source_sha"]
        known = {e["edge_id"]: e for e in versions[sha]["edges"]}
        assert len(version["routes"]) == 15
        assert {r["ROUTE_ID"] for r in version["routes"]} == {
            f"R{number:02}" for number in range(1, 16)
        }
        for route in version["routes"]:
            assert route["SOURCE_VERSION"] == sha
            for eid in route["CALL_CHAIN_EDGES"]:
                assert eid in known
                assert known[eid]["source_sha"] == sha
                assert known[eid]["caller_file_sha256"]
                assert known[eid]["callee_source_evidence"]["source_sha"] == sha
            for check in route["FORWARD_REVERSE_CROSSCHECK"]:
                assert check["forward"] is True and check["reverse"] is True
            assert route["SAFETY_CONTRACT_STATUS"] != "PASS"
            if route["ROUTE_ID"] == "R15":
                assert route["HISTORICAL_ORIGIN"] == "NOT_RECOVERABLE_FROM_AVAILABLE_SOURCE"
            elif route["ROUTE_ID"] != "R13":
                assert route["CALL_CHAIN_EDGES"] or route["SOURCE_EVIDENCE"]
    return True


@pytest.fixture
def package():
    return (
        json.loads((ROOT / "P42R_INTERNAL_CALL_EDGES.json").read_text()),
        json.loads((ROOT / "P42R_ROUTE_EVIDENCE_MATRIX.json").read_text()),
    )


def test_thirty_route_binding_and_bidirectional_consistency(package):
    assert validate(*package)


@pytest.mark.parametrize("fault", ["wrong_version", "missing_edge", "safety_pass", "empty_route"])
def test_corrupt_route_cannot_be_accepted(package, fault):
    edges, matrix = copy.deepcopy(package)
    route = matrix["versions"][0]["routes"][1]
    if fault == "wrong_version":
        route["SOURCE_VERSION"] = matrix["versions"][1]["source_sha"]
    elif fault == "missing_edge":
        route["CALL_CHAIN_EDGES"].append("made-up-edge")
    elif fault == "safety_pass":
        route["SAFETY_CONTRACT_STATUS"] = "PASS"
    else:
        route["CALL_CHAIN_EDGES"] = []
        route["SOURCE_EVIDENCE"] = []
    with pytest.raises(AssertionError):
        validate(edges, matrix)


def test_existing_lease_is_not_store_authorization(package):
    _, matrix = package
    for version in matrix["versions"]:
        service, cli = version["routes"][:2]
        assert service["LEASE_ACQUIRE_PATH"]
        assert service["SAFETY_CONTRACT_STATUS"] == "FAIL_EXISTING_SOURCE"
        assert cli["LEASE_ACQUIRE_PATH"] == []
        assert cli["CHECKPOINT_WRITES"]
        assert cli["CLASSIFICATION"] == "PROVEN_DEFECTIVE_INTERNAL_PATH"


def test_no_historical_origin_or_production_credit(package):
    _, matrix = package
    for version in matrix["versions"]:
        restored = version["routes"][-1]
        assert "NOT_RECOVERABLE_FROM_AVAILABLE_SOURCE" in restored["EXTERNAL_BOUNDARIES"]
        assert restored["PATH_RESOLUTION_STATUS"] == "NOT_APPLICABLE_HISTORICAL"


@pytest.mark.parametrize("fault", ["empty", "missing", "duplicate", "made_up_route"])
def test_version_inventory_cannot_pass_vacuously(package, fault):
    edges, matrix = copy.deepcopy(package)
    if fault == "empty":
        edges["versions"] = []
        matrix["versions"] = []
    elif fault == "missing":
        matrix["versions"].pop()
    elif fault == "duplicate":
        matrix["versions"][1] = matrix["versions"][0]
    else:
        matrix["versions"][0]["routes"][0]["ROUTE_ID"] = "NOT_A_ROUTE"
    with pytest.raises(AssertionError):
        validate(edges, matrix)


def test_direct_store_exceptions_are_not_claimed_as_engine_recovery(package):
    _, matrix = package
    for version in matrix["versions"]:
        store = next(r for r in version["routes"] if r["ROUTE_ID"] == "R11")
        assert store["EXCEPTION_PROPAGATION"] == (
            "Exception escapes direct Store caller; retry is not certified"
        )
        assert store["RETRY_PATH"].startswith("Direct caller retry not proven")
