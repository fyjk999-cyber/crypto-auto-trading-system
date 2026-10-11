"""Emit bounded static candidates, not silently authenticated dynamic edges."""

import json
import sys
from pathlib import Path

from scripts.p41_source_inventory import VERSIONS, git
from scripts.p42r_callgraph import index_sources, reachable, resolve_edges


def build(repo):
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads((root / "docs/P42_TRACKED_SOURCE_COMPLETENESS.json").read_text())
    old_routes = json.loads((root / "docs/P42_CHECKPOINT_CALLGRAPH.json").read_text())
    all_versions = []
    sink_versions = []
    unresolved_versions = []
    route_versions = []
    for version, old in zip(frozen["versions"], old_routes["versions"], strict=True):
        sha = version["source_sha"]
        assert sha in VERSIONS and old["source_sha"] == sha
        sources = {
            f["file_path"]: git(repo, "show", f"{sha}:{f['file_path']}")
            for f in version["tracked_source_files"] if f["file_path"].endswith(".py")
        }
        index = index_sources(sources, sha)
        edges = resolve_edges(index)
        component_paths = {
            "src/shared_market_history/storage/checkpoint_store.py",
            "src/shared_market_history/storage/atomic.py",
            "src/shared_market_history/storage/writer_lease.py",
        }
        seeds = {
            symbol for symbol, (module, _, _) in index["definitions"].items()
            if index["modules"][module]["path"] in component_paths
        }
        relevant = reachable(edges, seeds, reverse=True)
        selected = [e for e in edges if e["caller_id"] in relevant]
        unresolved = [e for e in selected if e["resolution_method"] == "UNRESOLVED"]
        registry = []
        for symbol in sorted(seeds):
            module, name, node = index["definitions"][symbol]
            registry.append(dict(
                definition_id=symbol, source_sha=sha,
                file=index["modules"][module]["path"], function=name,
                line=node.lineno, end_line=node.end_lineno,
                file_sha256=index["modules"][module]["digest"],
                classification="COMPONENT_DEFINITION_REQUIRES_SINK_CLASSIFICATION",
            ))
        all_versions.append(dict(
            source_sha=sha, edges=selected,
            interpretation="STATIC_CANDIDATES_NOT_MANUAL_ACCEPTANCE",
            selection="REVERSE_CLOSURE_OF_THREE_COMPONENTS; DYNAMIC_CROSSINGS_PENDING",
        ))
        sink_versions.append(dict(source_sha=sha, definitions=registry))
        unresolved_versions.append(dict(
            source_sha=sha, edges=unresolved,
            meaning="UNRESOLVED_IN_SELECTED_FUNCTIONS; NOT_ALL_HIGH_RISK_EDGES_ENUMERATED",
            external_boundaries=["ARBITRARY_PUBLIC_INJECTION", "INSTALLED_WRAPPERS",
                                 "THIRD_PARTY_DISPATCH", "HISTORICAL_RESTORED_WRITER"],
        ))
        routes = []
        for number, route in enumerate(old["known_routes"], 1):
            routes.append(dict(
                route_id=f"R{number:02}", source_version=sha,
                entrypoint=route["ENTRYPOINT"], source_file=route["SOURCE_FILE"],
                entry_function=route["FUNCTION"],
                prior_route_reference="P42_CHECKPOINT_CALLGRAPH.json",
                prior_chain_not_new_proof=route["CALL_CHAIN"],
                path_resolution_status="PENDING_FUNCTION_EDGE_RECONCILIATION",
                safety_contract_status="NOT_ACCEPTED_EXISTING_DEFECTS",
                classification="PARTIALLY_RESOLVED_INTERNAL_PATH" if number != 15
                else "UNRESOLVED_DYNAMIC_INTERNAL_PATH",
                call_chain_edges=[], source_evidence=[], fixture_evidence=[],
            ))
        route_versions.append(dict(source_sha=sha, routes=routes))
    outputs = {
        "P42R_INTERNAL_CALL_EDGES.json": all_versions,
        "P42R_CHECKPOINT_SINK_REGISTRY.json": sink_versions,
        "P42R_DYNAMIC_UNRESOLVED_EDGES.json": unresolved_versions,
        "P42R_ROUTE_EVIDENCE_MATRIX.json": route_versions,
    }
    for name, versions in outputs.items():
        (root / "docs" / name).write_text(json.dumps(dict(
            schema_version=1, state="WORKING_NOT_ACCEPTED",
            internal_source_evidence_closure="BLOCKED_PENDING_MANUAL_RECONCILIATION",
            versions=versions,
        ), indent=2, sort_keys=True) + "\n")
    print(json.dumps({"versions": [{
        "sha": v["source_sha"], "selected_static_edges": len(v["edges"])
    } for v in all_versions], "acceptance": "NOT_COMPLETE"}))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m scripts.p42r_build_evidence PINNED_GIT_REPO")
    build(sys.argv[1])
