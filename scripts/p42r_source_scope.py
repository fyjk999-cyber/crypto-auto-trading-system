"""Verify the frozen P4.2 source census against exact Git bytes, without imports."""

import hashlib
import json
import sys
from pathlib import Path

from scripts.p41_source_inventory import VERSIONS, git


def verify_scope(index, reader, enumerator):
    if index.get("schema_version") != 1 or type(index["schema_version"]) is not int:
        raise ValueError("unsupported index schema")
    versions = index.get("versions", [])
    if [v.get("source_sha") for v in versions] != list(VERSIONS):
        raise ValueError("version identity/order mismatch")
    result = []
    for version in versions:
        sha = version["source_sha"]
        records = version["tracked_source_files"]
        paths = [f["file_path"] for f in records]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate source path")
        expected = {
            p for p in enumerator(sha) if p.endswith((".py", ".sh", ".plist"))
        } | {"pyproject.toml"}
        if set(paths) != expected:
            raise ValueError("tracked source enumeration mismatch")
        files = []
        for record in records:
            path = record["file_path"]
            raw = reader(sha, path)
            digest = hashlib.sha256(raw).hexdigest()
            if digest != record["file_sha256"] or len(raw) != record["bytes"]:
                raise ValueError(f"source byte mismatch: {sha}:{path}")
            if record["parse_status"] not in {"PASS", "NOT_PYTHON"}:
                raise ValueError(f"unparsed input: {sha}:{path}")
            files.append(
                dict(
                    file_path=path,
                    file_sha256=digest,
                    bytes=len(raw),
                    role="TEST_ONLY" if path.startswith("tests/") else "SOURCE_ONLY",
                    parse_status=record["parse_status"],
                )
            )
        result.append(dict(source_sha=sha, source_files=files, count=len(files)))
    return dict(
        schema_version=1,
        versions=result,
        tracked_source_file_enumeration="PASS_EXACT_GIT_BYTES",
        count_meaning="TWO_SEPARATE_VERSION_COUNTS_NOT_COVERAGE_RATIO",
        internal_source_evidence_closure="NOT_ACCEPTED_CALLGRAPH_PENDING",
        runtime_entrypoint_completeness="NOT_PROVEN",
        production_file_reads=0,
    )


def main(repo):
    root = Path(__file__).resolve().parents[1]
    frozen = root / "docs/P42_TRACKED_SOURCE_COMPLETENESS.json"
    raw = frozen.read_bytes()
    result = verify_scope(
        json.loads(raw),
        lambda sha, path: git(repo, "show", f"{sha}:{path}"),
        lambda sha: git(repo, "ls-tree", "-r", "--name-only", sha).decode().splitlines(),
    )
    result["input_index_sha256"] = hashlib.sha256(raw).hexdigest()
    result["frozen_engineering_base"] = "2a7ff3319e5c366f571e6ebcac290c2168ed02a4"
    target = root / "docs/P42R_SOURCE_SCOPE_MANIFEST.json"
    target.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "status": "PASS_SCOPE_ONLY", "counts": [v["count"] for v in result["versions"]]
    }))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m scripts.p42r_source_scope PINNED_GIT_REPO")
    main(sys.argv[1])
