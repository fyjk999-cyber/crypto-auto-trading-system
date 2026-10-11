"""Byte-exact, offline Git import into a non-runtime research candidate only."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

SOURCE_SHA = "ff73e0c27a7a71a6e905beb13c60195e8482ea6a"
FILES = [f"docs/research/model-library/v2/{name}" for name in (
    "00_INDEX.md", "01_STOCHASTIC_VOLATILITY.md", "02_STATE_MEAN_REVERSION.md",
    "03_MICROSTRUCTURE_EVENTS.md", "04_PORTFOLIO_TAIL_RISK.md",
    "05_EXECUTION_ML_VALIDATION.md", "06_EVIDENCE_CASES.md",
)] + [f"docs/research/standby/lowrisk/{name}" for name in (
    "MODEL_KB.md", "HARNESS_MONITOR.md",
)]


def no_symlinks(path: Path) -> None:
    if not path.is_absolute():
        raise ValueError("absolute path required")
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError("symlink boundary")


def validate_models(payloads: dict[str, bytes]) -> list[str]:
    if set(payloads) != set(FILES):
        raise ValueError("exact nine files required")
    index = payloads[FILES[0]].decode("utf-8")
    indexed = re.findall(r"^\| (M\d{2}) \|", index, re.M)
    cards = []
    for name in FILES[1:6]:
        text = payloads[name].decode("utf-8")
        cards.extend(re.findall(r"^## (M\d{2})\b", text, re.M))
    expected = [f"M{i:02}" for i in range(1, 25)]
    if sorted(indexed) != expected or sorted(cards) != expected:
        raise ValueError("missing, duplicate or unexpected model IDs")
    if "## M24 Deflated Sharpe Ratio" not in payloads[FILES[5]].decode("utf-8"):
        raise ValueError("M24 identity mismatch")
    return expected


def import_candidate(source: Path, workspace: Path) -> Path:
    no_symlinks(workspace)
    root = workspace / "docs/research/knowledge-candidates"
    no_symlinks(root)
    target = root / SOURCE_SHA
    no_symlinks(target)
    payloads, records = {}, []
    for name in FILES:
        obj = f"{SOURCE_SHA}:{name}"
        data = subprocess.check_output(["git", "-C", str(source), "show", obj])
        blob = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", obj], text=True
        ).strip()
        payloads[name] = data
        records.append({"source_path": name, "git_blob_sha": blob,
                        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    models = validate_models(payloads)
    if target.exists():
        for name, data in payloads.items():
            path = target / name
            no_symlinks(path)
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError("existing candidate differs; preserve it")
        manifest_path = target / "MODEL_LIBRARY_V2_IMPORT_MANIFEST.json"
        no_symlinks(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("source_commit") != SOURCE_SHA or manifest.get("files") != records:
            raise ValueError("manifest mismatch")
        return target
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".kb-stage-", dir=root))
    for name, data in payloads.items():
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if path.read_bytes() != data:
            raise ValueError("byte verification failed")
    manifest = {"source_repository": "fyjk999-cyber/crypto-auto-trading-system",
                "source_commit": SOURCE_SHA, "files": records, "models": models,
                "knowledge_mode": "REFERENCE_ONLY", "local_kb_target": "UNCONFIRMED",
                "model_auto_activation": False, "model_auto_training": False,
                "factor_auto_replacement": False, "strategy_auto_optimization": False,
                "llm_prompt_auto_injection": False, "runtime_publication": False}
    (staging / "MODEL_LIBRARY_V2_IMPORT_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # Publish only this previously absent candidate; never replace existing bytes.
    if target.exists():
        raise ValueError("publication conflict; staging preserved")
    # macOS exclusive rename also refuses a destination appearing during publication.
    import ctypes
    import os

    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renamex_np
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(os.fsencode(staging), os.fsencode(target), 4) != 0:  # RENAME_EXCL
        raise OSError(ctypes.get_errno(), "exclusive publication failed; staging preserved")
    return target


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    print(import_candidate(args.source, Path(__file__).resolve().parents[1]))
