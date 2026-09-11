"""I06: v1 ``growth_compressions`` duplicate path audit.

Classification of every current reference:

* ``learning/growth_models.py``      -> schema definition (test/draft support)
* ``learning/growth_knowledge.py``   -> LEGACY_WRITE (v1 ``compress`` only)
* ``learning/growth_metrics.py``     -> LEGACY_READ (metrics only)
* ``tests/**``                       -> TEST_ONLY

Runtime/trading path must have zero reads and zero writes.  The canonical card
truth is ``ai_compressed_experience`` only.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "crypto_trader"

RUNTIME_FILES = (
    "runtime/bootstrap.py",
    "runtime/engine.py",
    "llm_chief/runtime_strategy.py",
    "llm_chief/context_loader.py",
    "learning/growth_card_retrieval.py",
    "learning/growth_v2_runtime.py",
    "learning/growth_experience.py",
)

LEGACY_TOKENS = ("growth_compressions", "GrowthCompressionORM")

ALLOWED_REFERENCE_FILES = {
    "learning/growth_models.py",
    "learning/growth_knowledge.py",
    "learning/growth_metrics.py",
    # v1 G06-style context loader reads legacy compressed experience for
    # backwards compatibility; it is not on the canonical V2 runtime path.
    "learning/growth_retrieval.py",
}


def test_runtime_paths_have_zero_legacy_card_reads_or_writes():
    for relative in RUNTIME_FILES:
        text = (SRC / relative).read_text(encoding="utf-8")
        for token in LEGACY_TOKENS:
            assert token not in text, f"{relative} references legacy card path {token}"


def test_only_classified_files_reference_v1_compression_table():
    references: set[str] = set()
    for path in list(SRC.rglob("*.py")) + list((REPO / "tests").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in LEGACY_TOKENS):
            references.add(str(path.relative_to(REPO)))
    unexpected = {
        ref
        for ref in references
        if ref.startswith("src/") and not ref.startswith("src/crypto_trader/")
    }
    assert not unexpected
    remaining = {
        ref
        for ref in references
        if not ref.startswith("tests/")
        and not ref.startswith("src/crypto_trader/learning/")
    }
    assert not remaining, f"unclassified legacy references: {sorted(remaining)}"
    src_refs = {
        ref.split("src/crypto_trader/", 1)[1]
        for ref in references
        if ref.startswith("src/crypto_trader/")
    }
    assert src_refs <= ALLOWED_REFERENCE_FILES, f"unexpected src references: {src_refs}"


def test_canonical_card_retrieval_uses_only_ai_compressed_experience():
    source = (SRC / "learning" / "growth_card_retrieval.py").read_text(encoding="utf-8")
    assert "AICompressedExperienceORM" in source
    assert "growth_compressions" not in source
    assert "GrowthCompressionORM" not in source


def test_no_runtime_or_scheduler_calls_v1_compress():
    for relative in (
        "runtime/bootstrap.py",
        "runtime/engine.py",
        "governance/scheduler.py",
        "llm_chief/runtime_strategy.py",
    ):
        text = (SRC / relative).read_text(encoding="utf-8")
        assert ".compress(" not in text, f"{relative} calls v1 compress"
