import copy

import pytest

from scripts.p42_checkpoint_map import build


def inputs():
    return (
        {"versions": [{"source_sha": "fixed", "files": [{"file": "x.py", "sha256": "h"}]}]},
        {
            "versions": [
                {
                    "source_sha": "fixed",
                    "tracked_source_files": [
                        {
                            "file_path": "x.py",
                            "file_sha256": "h",
                            "calls": [
                                {"target": "alias.checkpoint_save", "function": "f", "line": 1}
                            ],
                        }
                    ],
                }
            ]
        },
        {"versions": [{"source_sha": "fixed", "entries": []}]},
    )


def test_map_does_not_upgrade_lexical_source_to_ready():
    old, new, routes = inputs()
    for record in (old, new, routes):
        second = copy.deepcopy(record["versions"][0])
        second["source_sha"] = "second-fixed"
        record["versions"].append(second)
    result = build(old, new, routes)
    assert result["source_and_contract_ready"] == "NO"
    version = result["versions"][0]
    assert version["count_reconciliation"]["original_source_bytes_unchanged"]
    assert len(version["lexical_boundary_calls"]) == 1


def test_source_binding_mismatch_rejected():
    old, new, routes = copy.deepcopy(inputs())
    new["versions"][0]["source_sha"] = "different"
    with pytest.raises(AssertionError):
        build(old, new, routes)
