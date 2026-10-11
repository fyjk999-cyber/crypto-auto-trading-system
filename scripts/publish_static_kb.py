"""Publish the already verified nine-document candidate; never wire runtime knowledge."""
import ctypes
import hashlib
import json
import os
import tempfile
from pathlib import Path

from import_reference_kb import FILES, SOURCE_SHA, no_symlinks, validate_models

SOURCE_MANIFEST_SHA = "721b807ddaa69918dc2b652760da170d1bf94de775b85e07468e07faaf6f6a5f"


def publish(workspace):
    source = workspace / "docs/research/knowledge-candidates" / SOURCE_SHA
    root = workspace / "docs/research/knowledge-library/v2"
    target = root / SOURCE_SHA
    for path in (source, root, target):
        no_symlinks(path)
    manifest_path = source / "MODEL_LIBRARY_V2_IMPORT_MANIFEST.json"
    no_symlinks(manifest_path)
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != SOURCE_MANIFEST_SHA:
        raise ValueError("pinned candidate manifest changed")
    manifest = json.loads(manifest_bytes)
    names = [ref["source_path"] for ref in manifest["files"]]
    if sorted(names) != sorted(FILES):
        raise ValueError("exact source inventory")
    if manifest["source_repository"] != "fyjk999-cyber/crypto-auto-trading-system":
        raise ValueError("source repository")
    if manifest["source_commit"] != SOURCE_SHA or manifest["knowledge_mode"] != "REFERENCE_ONLY":
        raise ValueError("source admission")
    for flag in ("model_auto_activation", "model_auto_training", "factor_auto_replacement",
                 "strategy_auto_optimization", "llm_prompt_auto_injection", "runtime_publication"):
        if manifest[flag] is not False:
            raise ValueError("source safety flags")
    payloads, destinations = {}, {}
    for ref in manifest["files"]:
        name = ref["source_path"]
        src = source / name
        no_symlinks(src)
        data = src.read_bytes()
        blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if hashlib.sha256(data).hexdigest() != ref["sha256"] or blob != ref["git_blob_sha"]:
            raise ValueError("source bytes drift")
        payloads[name] = data
        section = "model-library" if "/model-library/" in name else "lowrisk"
        destinations[f"{section}/{src.name}"] = data
    if manifest["models"] != validate_models(payloads):
        raise ValueError("model metadata mismatch")
    if len(destinations) != 9:
        raise ValueError("duplicate destination")
    admission = {"schema_version": 1, "source_commit": SOURCE_SHA,
                 "source_repository": manifest["source_repository"], "files": manifest["files"],
                 "mode": "STATIC_REFERENCE_ONLY", "runtime_integration": False,
                 "models": manifest["models"]}
    destinations["IMPORT_MANIFEST.json"] = (
        json.dumps(admission, ensure_ascii=False, indent=2) + "\n").encode()
    if target.exists():
        actual = {str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()}
        if actual != set(destinations):
            raise ValueError("existing publication inventory differs")
        for name, data in destinations.items():
            path = target / name
            no_symlinks(path)
            if path.read_bytes() != data:
                raise ValueError("existing publication differs; preserved")
        return target
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".static-stage-", dir=root))
    for name, data in destinations.items():
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if path.read_bytes() != data:
            raise ValueError("staging mismatch")
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renamex_np
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(os.fsencode(staging), os.fsencode(target), 4) != 0:
        raise OSError(ctypes.get_errno(), "exclusive publication failed; staging preserved")
    return target


if __name__ == "__main__":
    print(publish(Path(__file__).resolve().parents[1]))
