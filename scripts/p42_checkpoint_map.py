"""Enrich fixed-source indexes; unknown receivers are deliberately unresolved."""

import json
import re
from pathlib import Path


def checkpoint_calls(version):
    return [
        dict(file_path=f["file_path"], file_sha256=f["file_sha256"], **c)
        for f in version["tracked_source_files"]
        for c in f.get("calls", [])
        if re.search(
            r"checkpoint|ckpt|WriterLease|writer_lease|atomic_write|fsync|read_json", c["target"]
        )
    ]


def reconcile(old, new):
    old_files = {f["file"]: f for f in old["files"]}
    new_files = {f["file_path"]: f for f in new["tracked_source_files"]}
    return dict(
        old_file_count=len(old_files),
        new_file_count=len(new_files),
        old_function_count=sum(len(f.get("functions", [])) for f in old_files.values()),
        old_selected_call_count=sum(len(f.get("calls", [])) for f in old_files.values()),
        additional_files=[
            dict(
                file_path=p,
                file_sha256=new_files[p]["file_sha256"],
                classification="TRACKED_ARTIFACT_CONTENT_AUDITED",
                proof_reference="P42_ARTIFACT_AUDIT_NOTES.md",
            )
            for p in sorted(new_files.keys() - old_files.keys())
        ],
        original_source_bytes_unchanged=all(
            f["sha256"] == new_files[p]["file_sha256"] for p, f in old_files.items()
        ),
        count_meaning="FUNCTIONS_INCLUDE_TESTS; OLD_CALLS_REGEX_SUBSET_NOT_FULL_CALLGRAPH",
    )


def build(old, new, routes):
    versions = []
    for before, after, matrix in zip(
        old["versions"], new["versions"], routes["versions"], strict=True
    ):
        assert before["source_sha"] == after["source_sha"] == matrix["source_sha"]
        entries = []
        for route in matrix["entries"]:
            entries.append(
                dict(
                    **route,
                    ROUTE_ORIGIN="P41_MANUAL_ROUTE_RETAINED_NOT_NEWLY_CERTIFIED",
                    RETRY_BOUNDARY=(
                        "NO_PERSISTENT_OPERATION_ID; AUTOMATIC_UNKNOWN_COMMIT_RETRY_NOT_APPROVED"
                    ),
                    ERROR_RECOVERY="INVALID_LOAD_DEFAULTS_AND_POST_REPLACE_UNCERTAINTY_UNFIXED",
                    FUTURE_ADMISSION="OWNERSHIP_CAS_TYPED_LOAD_DURABILITY_CONTRACTS_REQUIRE_IMPLEMENTATION",
                )
            )
        versions.append(
            dict(
                source_sha=after["source_sha"],
                count_reconciliation=reconcile(before, after),
                known_routes=entries,
                lexical_boundary_calls=checkpoint_calls(after),
                semantic_closure="BLOCKED_INTERNAL_RECEIVER_AND_CALLER_REVIEW_PENDING",
            )
        )
    a, b = [{f["file_path"]: f for f in v["tracked_source_files"]} for v in new["versions"]]
    changed = [
        dict(
            file_path=p,
            kind="ADDED" if p not in a else "REMOVED" if p not in b else "MODIFIED",
            before_sha256=a.get(p, {}).get("file_sha256"),
            after_sha256=b.get(p, {}).get("file_sha256"),
            function_count_before=len(a.get(p, {}).get("functions", [])),
            function_count_after=len(b.get(p, {}).get("functions", [])),
            semantic_change="REQUIRES_FUNCTION_LEVEL_REVIEW",
        )
        for p in sorted(a.keys() | b.keys())
        if a.get(p, {}).get("file_sha256") != b.get(p, {}).get("file_sha256")
    ]
    return dict(
        schema_version=1,
        versions=versions,
        version_file_delta=changed,
        source_and_contract_ready="NO",
        full_runtime_closure="NOT_PROVEN",
    )


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "docs"
    result = build(
        *(
            json.loads((root / name).read_text())
            for name in (
                "P41_SOURCE_INVENTORY.json",
                "P42_TRACKED_SOURCE_COMPLETENESS.json",
                "P41_ENTRYPOINT_MATRIX.json",
            )
        )
    )
    (root / "P42_CHECKPOINT_CALLGRAPH.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "changed_files": len(result["version_file_delta"]),
                "reconciliation": [v["count_reconciliation"] for v in result["versions"]],
            }
        )
    )
