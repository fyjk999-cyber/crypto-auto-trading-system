import copy
import hashlib

import pytest

from scripts.p41_source_inventory import VERSIONS
from scripts.p42r_source_scope import verify_scope


@pytest.fixture
def census():
    raw = b"def sink():\n    pass\n"
    files = {
        "src/example.py": raw,
        "pyproject.toml": b"[project]\nname='fixture'\n",
    }
    index = dict(
        schema_version=1,
        versions=[
            dict(
                source_sha=sha,
                tracked_source_files=[
                    dict(
                        file_path=p,
                        file_sha256=hashlib.sha256(b).hexdigest(),
                        bytes=len(b),
                        parse_status="PASS" if p.endswith(".py") else "NOT_PYTHON",
                    )
                    for p, b in files.items()
                ],
            )
            for sha in VERSIONS
        ],
    )
    return index, lambda sha, p: files[p], lambda sha: list(files)


def test_exact_scope_is_not_semantic_or_runtime_acceptance(census):
    index, reader, enumerator = census
    before = copy.deepcopy(index)
    result = verify_scope(index, reader, enumerator)
    assert index == before
    assert [v["count"] for v in result["versions"]] == [2, 2]
    assert result["internal_source_evidence_closure"] == "NOT_ACCEPTED_CALLGRAPH_PENDING"
    assert result["runtime_entrypoint_completeness"] == "NOT_PROVEN"


@pytest.mark.parametrize(
    "fault", ["version", "schema_bool", "hash", "bytes", "missing", "duplicate", "parse"]
)
def test_bad_frozen_input_fails_closed(census, fault):
    index, reader, enumerator = census
    record = index["versions"][0]["tracked_source_files"][0]
    if fault == "version":
        index["versions"][0]["source_sha"] = VERSIONS[1]
    elif fault == "schema_bool":
        index["schema_version"] = True
    elif fault == "hash":
        record["file_sha256"] = "0" * 64
    elif fault == "bytes":
        record["bytes"] += 1
    elif fault == "missing":
        index["versions"][0]["tracked_source_files"].pop()
    elif fault == "duplicate":
        index["versions"][0]["tracked_source_files"].append(dict(record))
    else:
        record["parse_status"] = "UNKNOWN"
    with pytest.raises(ValueError):
        verify_scope(index, reader, enumerator)


def test_git_bytes_changed_after_census_fails(census):
    index, reader, enumerator = census
    with pytest.raises(ValueError, match="source byte mismatch"):
        verify_scope(index, lambda sha, path: reader(sha, path) + b"\n", enumerator)
