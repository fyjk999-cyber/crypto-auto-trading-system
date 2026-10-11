"""Pinned source index only; never import or execute audited source.

shortcut: lexical receiver resolution remains unknown; independent semantic
review is required before source/contract readiness can be accepted.
"""

import ast
import hashlib
import json
import sys
from pathlib import Path

from scripts.p41_source_inventory import VERSIONS, git


class Calls(ast.NodeVisitor):
    def __init__(self):
        self.scope = []
        self.functions = []
        self.calls = []
        self.imports = []

    def visit_ClassDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node):
        self.scope.append(node.name)
        self.functions.append(dict(name=".".join(self.scope), line=node.lineno))
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        self.calls.append(
            dict(
                function=".".join(self.scope) or "<module>",
                line=node.lineno,
                target=ast.unparse(node.func),
                source=ast.unparse(node),
                semantic_resolution="UNCLASSIFIED_LEXICAL_CALL",
            )
        )
        self.generic_visit(node)

    def visit_Import(self, node):
        self.imports.append(dict(line=node.lineno, source=ast.unparse(node)))

    visit_ImportFrom = visit_Import


def inventory(repo, sha):
    names = git(repo, "ls-tree", "-r", "--name-only", sha).decode().splitlines()
    sources = [p for p in names if p.endswith((".py", ".sh", ".plist"))]
    sources.append("pyproject.toml")
    files = []
    for path in sources:
        raw = git(repo, "show", f"{sha}:{path}")
        record = dict(
            source_sha=sha,
            file_path=path,
            file_sha256=hashlib.sha256(raw).hexdigest(),
            bytes=len(raw),
        )
        if path.endswith(".py"):
            visitor = Calls()
            try:
                visitor.visit(ast.parse(raw.decode(), filename=path))
                record.update(
                    parse_status="PASS",
                    functions=visitor.functions,
                    calls=visitor.calls,
                    imports=visitor.imports,
                )
            except (SyntaxError, UnicodeDecodeError) as exc:
                record.update(parse_status="UNKNOWN", error_type=type(exc).__name__)
        else:
            record.update(parse_status="NOT_PYTHON", text=raw.decode())
        files.append(record)
    return dict(
        source_sha=sha,
        tracked_source_files=files,
        source_inventory_coverage="ALL_FIXED_EXTENSION_SOURCE_BYTES_READ",
        semantic_callgraph_coverage="BLOCKED_UNCLASSIFIED_CALLS",
        external_runtime_closure="NOT_PROVEN",
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m scripts.p42_source_inventory PINNED_GIT_REPOSITORY")
    result = dict(schema_version=1, versions=[inventory(sys.argv[1], s) for s in VERSIONS])
    target = Path(__file__).resolve().parents[1] / "docs/P42_TRACKED_SOURCE_COMPLETENESS.json"
    target.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(
        json.dumps(
            {
                "artifact": str(target),
                "files": [len(v["tracked_source_files"]) for v in result["versions"]],
            }
        )
    )
