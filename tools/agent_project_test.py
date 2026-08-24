#!/usr/bin/env python3
"""Project-local agent-project-test gate.

Runs code test (ruff), functional/unit tests, integration tests, regression
tests (chaos + e2e), and SPAC requirement coverage sequentially. Any failure
stops the gate.
"""
import subprocess
import sys


def run(name: str, args: list[str]) -> bool:
    print(f"\n=== agent-project-test: {name} ===")
    proc = subprocess.run(args)
    return proc.returncode == 0


def main() -> int:
    steps = [
        ("code test (lint)", [sys.executable, "-m", "ruff", "check", "src", "tests"]),
        ("functional/unit test", [sys.executable, "-m", "pytest", "tests/unit", "tests/runtime_unit", "-q"]),
        ("integration test", [sys.executable, "-m", "pytest", "tests/integration", "-q"]),
        (
            "regression test (chaos + e2e)",
            [sys.executable, "-m", "pytest", "tests/chaos", "tests/e2e", "-q"],
        ),
        ("SPAC requirement coverage", [sys.executable, "-m", "pytest", "tests/spac", "-q"]),
    ]
    for name, args in steps:
        if not run(name, args):
            print(f"\nagent-project-test: FAIL at {name}")
            return 1
    print("\nagent-project-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
