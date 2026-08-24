#!/usr/bin/env python3
"""Project-local lean-brainstorm-grill gate (auto mode).

The full grill is recorded in docs/phase1_brainstorm.md. This gate verifies the
decision record exists and is complete before implementation work continues.
"""
from pathlib import Path

REQUIRED = [
    "Product boundary",
    "Architecture grill",
    "Final architecture decision",
    "SPAC traceability",
]


def main() -> int:
    doc = Path("docs/phase1_brainstorm.md")
    if not doc.exists():
        print("FAIL: docs/phase1_brainstorm.md missing")
        return 1
    text = doc.read_text()
    for section in REQUIRED:
        if section not in text:
            print(f"FAIL: missing section {section}")
            return 1
    print("lean-brainstorm-grill: PASS (auto)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
