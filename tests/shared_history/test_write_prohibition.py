"""Write prohibition and administrative-path prohibition, proven by static analysis.

Required:
    LOWRISK_SHARED_HISTORY_WRITE_PATHS            = 0
    LOWRISK_SHARED_HISTORY_ADMIN_PATHS            = 0
    LOWRISK_DIRECT_PARQUET_PATHS                  = 0
    LOWRISK_DIRECT_DUCKDB_PATHS                   = 0
    LOWRISK_CHECKPOINT_MUTATION_PATHS             = 0
    NO_INSERT_NO_UPDATE_NO_DELETE_NO_ALTER        = PASS
    NO_POST_NO_PUT_NO_PATCH_NO_DELETE_HTTP        = PASS

The scanner is probed against synthetic violators first, so every rule is proven
able to fire. A rule that cannot fail would be worse than a missing rule.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "crypto_trader" / "shared_history"
SOURCE_FILES = sorted(PACKAGE.glob("*.py"))

# Modules LowRisk must not import: storage engines, writers, or the producer package.
FORBIDDEN_MODULES = {
    "duckdb",
    "pyarrow",
    "pyarrow.parquet",
    "polars",
    "sqlite3",
    "sqlalchemy",
    "shared_market_history",
    "psycopg2",
}

# Call/attribute names that would indicate a write or an administrative action.
FORBIDDEN_NAMES = {
    "write_parquet",
    "read_parquet",
    "to_parquet",
    "from_parquet",
    "write_dataset",
    "write_open_interest",
    "write_candles",
    "write_funding",
    "insert",
    "update",
    "delete",
    "upsert",
    "append",
    "overwrite",
    "truncate",
    "drop",
    "alter",
    "create_table",
    "attach",
    "compact",
    "prune",
    "retention_sweep",
    "backfill",
    "ingest",
    "acquire_lease",
    "writer_lease",
    "checkpoint_write",
    "mutate_checkpoint",
    "chmod",
    "chown",
    "unlink",
    "rmtree",
    "remove",
    "rmdir",
    "rename",
    "mkdir",
    "makedirs",
}

FORBIDDEN_SQL = ("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "DROP ", "CREATE TABLE", "ATTACH ")

# HTTP verbs the LowRisk transport must never use.
FORBIDDEN_HTTP_VERBS = {"POST", "PUT", "PATCH", "DELETE"}


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def scan_source(source: str) -> dict[str, list[str]]:
    """Return violations by rule for one module's source text."""
    tree = ast.parse(source)
    docstrings = _docstring_ids(tree)
    violations: dict[str, list[str]] = {
        "forbidden_import": [],
        "forbidden_name": [],
        "forbidden_sql": [],
        "forbidden_write_mode": [],
        "forbidden_http_verb": [],
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_MODULES:
                    violations["forbidden_import"].append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in FORBIDDEN_MODULES or module.split(".")[0] in {
                m.split(".")[0] for m in FORBIDDEN_MODULES
            }:
                violations["forbidden_import"].append(module)
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                violations["forbidden_name"].append(node.id)
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_NAMES:
                violations["forbidden_name"].append(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            upper = node.value.upper()
            for verb in FORBIDDEN_SQL:
                if verb in upper:
                    violations["forbidden_sql"].append(node.value[:60])
            if node.value in FORBIDDEN_HTTP_VERBS:
                violations["forbidden_http_verb"].append(node.value)
        elif isinstance(node, ast.keyword) and node.arg == "method":
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                if node.value.value.upper() in FORBIDDEN_HTTP_VERBS:
                    violations["forbidden_http_verb"].append(node.value.value)

    # open(...) must never use a writing mode.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "open":
                for arg in list(node.args[1:2]) + [
                    kw.value for kw in node.keywords if kw.arg == "mode"
                ]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if any(ch in arg.value for ch in ("w", "a", "x", "+")):
                            violations["forbidden_write_mode"].append(arg.value)

    return {rule: found for rule, found in violations.items() if found}


def http_method_literals(source: str) -> list[str]:
    """Observations, not violations: every HTTP verb literal present in the source."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                found.append(node.value)
        elif isinstance(node, ast.keyword) and node.arg == "method":
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                found.append(node.value.value.upper())
    return found


# ----------------------------------------------------------------------
# The scanner must be able to fire. Prove it on synthetic violators.
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "source,rule",
    [
        ("import duckdb\n", "forbidden_import"),
        ("import pyarrow.parquet as pq\n", "forbidden_import"),
        ("from shared_market_history.storage import ParquetStore\n", "forbidden_import"),
        ("store.write_parquet('x')\n", "forbidden_name"),
        ("con.execute('INSERT INTO t VALUES (1)')\n", "forbidden_sql"),
        ("con.execute('DELETE FROM candles')\n", "forbidden_sql"),
        ("open('x.parquet', 'wb')\n", "forbidden_write_mode"),
        ("open('x', mode='a')\n", "forbidden_write_mode"),
        (
            "import urllib.request\nurllib.request.Request(u, method='POST')\n",
            "forbidden_http_verb",
        ),
        ("Path('x').unlink()\n", "forbidden_name"),
    ],
)
def test_scanner_detects_violations(source, rule):
    assert rule in scan_source(source), f"scanner failed to detect {rule}"


def test_scanner_ignores_prose_in_docstrings():
    """The authority/provenance prose must not be mistaken for a write path."""
    source = '"""This module mentions Parquet, DuckDB, INSERT and checkpoints."""\n'
    assert scan_source(source) == {}


def test_scanner_still_reads_real_code_strings():
    source = '"""doc"""\nSQL = "INSERT INTO candles"\n'
    assert "forbidden_sql" in scan_source(source)


# ----------------------------------------------------------------------
# The real package
# ----------------------------------------------------------------------
def test_package_files_were_actually_found():
    names = {p.name for p in SOURCE_FILES}
    assert names == {"__init__.py", "adapter.py", "client.py", "readiness.py", "consumer.py"}, names


def test_no_write_or_admin_paths_in_package():
    all_violations: dict[str, list[str]] = {}
    for path in SOURCE_FILES:
        found = scan_source(path.read_text())
        if found:
            all_violations[path.name] = found
    assert all_violations == {}, f"write/admin paths detected: {all_violations}"


def test_only_get_is_used_as_an_http_method():
    """Exactly one HTTP method literal exists across the package, and it is GET."""
    literals: list[str] = []
    for path in SOURCE_FILES:
        literals.extend(http_method_literals(path.read_text()))
    assert literals, "no HTTP method literal found; the transport claim is unproven"
    assert set(literals) == {"GET"}


def test_no_reference_to_the_production_data_root():
    for path in SOURCE_FILES:
        text = path.read_text()
        assert "/Volumes/My PSSD" not in text, path.name
        assert "SharedMarketHistory/parquet" not in text, path.name


def test_no_filesystem_path_construction():
    """The consumer must not learn storage internals."""
    for path in SOURCE_FILES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in {"Path", "PurePath"}:
                pytest.fail(f"{path.name} constructs filesystem paths")
            if isinstance(node, ast.Attribute) and node.attr in {"resolve", "cwd", "home"}:
                pytest.fail(f"{path.name} touches the filesystem: {node.attr}")


def test_module_imports_nothing_from_the_producer_package():
    """Reuse is by vendored source, not by coupling to the producer's internals."""
    for path in SOURCE_FILES:
        text = path.read_text()
        assert "import shared_market_history" not in text, path.name
