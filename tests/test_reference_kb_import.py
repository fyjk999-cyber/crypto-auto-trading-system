import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "reference_import", Path(__file__).parents[1] / "scripts/import_reference_kb.py"
)
kb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kb)


def payload():
    data = {name: b"reference" for name in kb.FILES}
    data[kb.FILES[0]] = "\n".join(f"| M{i:02} | theory |" for i in range(1, 25)).encode()
    data[kb.FILES[1]] = "\n".join(f"## M{i:02} Theory" for i in range(1, 24)).encode()
    data[kb.FILES[5]] = b"## M24 Deflated Sharpe Ratio"
    return data


def test_complete_ids():
    assert len(kb.validate_models(payload())) == 24


@pytest.mark.parametrize(
    "fault", ["missing_file", "missing_id", "duplicate", "unexpected", "wrong_m24"]
)
def test_reject_incomplete_or_false_identity(fault):
    data = payload()
    if fault == "missing_file":
        del data[kb.FILES[-1]]
    elif fault == "missing_id":
        data[kb.FILES[1]] = data[kb.FILES[1]].replace(b"M01", b"N01")
    elif fault == "duplicate":
        data[kb.FILES[1]] += b"\n## M01 Duplicate"
    elif fault == "unexpected":
        data[kb.FILES[1]] += b"\n## M25 Unknown"
    else:
        data[kb.FILES[5]] = b"## M24 X24_MARKET_REGIME"
    with pytest.raises(ValueError):
        kb.validate_models(data)


def test_symlink_boundary(tmp_path):
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        kb.no_symlinks(tmp_path / "link" / "new")


def test_atomic_candidate_idempotence_and_preserved_edits(tmp_path, monkeypatch):
    data = payload()

    def git_output(args, **kwargs):
        if "show" in args:
            return data[args[-1].split(":", 1)[1]]
        return "a" * 40 + "\n"

    monkeypatch.setattr(kb.subprocess, "check_output", git_output)
    target = kb.import_candidate(tmp_path, tmp_path)
    assert kb.import_candidate(tmp_path, tmp_path) == target
    document = target / kb.FILES[0]
    document.write_bytes(b"user edit")
    with pytest.raises(ValueError):
        kb.import_candidate(tmp_path, tmp_path)
    assert document.read_bytes() == b"user edit"


def test_existing_symlink_refused_before_read(tmp_path, monkeypatch):
    data = payload()
    monkeypatch.setattr(kb.subprocess, "check_output", lambda args, **kwargs:
                        data[args[-1].split(":", 1)[1]] if "show" in args else "a" * 40 + "\n")
    target = kb.import_candidate(tmp_path, tmp_path)
    doc = target / kb.FILES[0]
    doc.unlink()
    doc.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError):
        kb.import_candidate(tmp_path, tmp_path)
