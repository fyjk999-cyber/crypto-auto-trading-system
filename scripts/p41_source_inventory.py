"""Enumerate pinned Git source without importing it or reading runtime state.

shortcut: lexical call targets are not an interprocedural proof; dynamic receivers
and external entrypoints require independent evidence before full closure.
"""

import ast
import hashlib
import json
import re
import subprocess
import sys

VERSIONS = ("25505ff15dd6acd623140d70c0a8eb216c59ea48", "b1a3f97b213d062ed70375ac7aedbd0d67745a0b")
FIELDS = (
    "completed",
    "dataset",
    "forward_bridge_start_ms",
    "forward_cursor",
    "forward_in_progress",
    "forward_latest",
    "last_error",
    "last_success_at",
    "newest_fetched",
    "next_cursor",
    "oldest_fetched",
    "retry_count",
    "source",
    "status",
    "symbol",
    "timeframe",
    "updated_at",
    "pause_reason",
    "restored_completed_at",
    "restored_reason",
)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args])


class References(ast.NodeVisitor):
    def __init__(self):
        self.scope = []
        self.functions = []
        self.calls = []
        self.fields = []
        self.imports = []

    def visit_ClassDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node):
        self.scope.append(node.name)
        self.functions.append(
            {"name": ".".join(self.scope), "line": node.lineno, "end_line": node.end_lineno}
        )
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        target = ast.unparse(node.func)
        # Retain lexical calls for every function, including callbacks/aliases.
        if re.search(
            r"checkpoint|ckpt|WriterLease|writer_lease|atomic_write|fsync|read_json|"
            r"cleanup_stale|submit|run_task|run_traced|start_background|serve_forever|"
            r"_backfill|_run_loop|getattr|setattr|eval|exec",
            target,
        ):
            self.calls.append(
                {
                    "function": ".".join(self.scope) or "<module>",
                    "line": node.lineno,
                    "target": target,
                    "arguments": [ast.unparse(arg) for arg in node.args],
                }
            )
        self.generic_visit(node)

    def visit_Import(self, node):
        self.imports.append({"line": node.lineno, "source": ast.unparse(node)})

    visit_ImportFrom = visit_Import

    def visit_Constant(self, node):
        if isinstance(node.value, str) and node.value in FIELDS:
            self.fields.append(
                {
                    "function": ".".join(self.scope) or "<module>",
                    "line": node.lineno,
                    "field": node.value,
                }
            )


def inventory(repo, version):
    names = git(repo, "ls-tree", "-r", "--name-only", version).decode().splitlines()
    selected = [
        name
        for name in names
        if name.startswith(("src/", "scripts/", "tests/"))
        and name.endswith((".py", ".sh", ".plist"))
    ]
    selected.append("pyproject.toml")
    outside = [
        name for name in names if name.endswith((".py", ".sh", ".plist")) and name not in selected
    ]
    if len(sys.argv) == 3:
        selected = [name for name in selected if name == sys.argv[2]]
    files = []
    for name in selected:
        raw = git(repo, "show", f"{version}:{name}")
        item = {
            "file": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "role": "TEST_ONLY" if name.startswith("tests/") else "SOURCE",
        }
        if name.endswith(".py"):
            visitor = References()
            visitor.visit(ast.parse(raw.decode(), filename=name))
            item.update(
                functions=visitor.functions,
                calls=visitor.calls,
                fields=visitor.fields,
                imports=visitor.imports,
            )
        else:
            item["text"] = raw.decode()
        files.append(item)
    # Other executable artifacts are named, not opened: their project scope is
    # not established, and several are historical non-SH recovery scripts.
    return {
        "source_sha": version,
        "files": files,
        "outside_scope_names": outside,
        "outside_scope_classification": "OUTSIDE_REPOSITORY_SCOPE_NOT_PROVEN_UNREACHABLE",
        "full_callgraph": "NOT_PROVEN",
        "metadata_exclusion_allowlist": [],
    }


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit("usage: p41_source_inventory.py SH_SOURCE_REPOSITORY [EXACT_SOURCE_FILE]")
    print(
        json.dumps(
            {"schema_version": 1, "versions": [inventory(sys.argv[1], sha) for sha in VERSIONS]},
            sort_keys=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
