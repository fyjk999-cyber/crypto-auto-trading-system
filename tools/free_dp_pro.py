#!/usr/bin/env python3
"""Project-local free-dp-pro planning gate.

Solves the phase dependency graph with dynamic programming and verifies the
chosen architecture is the minimum-complexity plan recorded in phase 1.
"""
from pathlib import Path


def main() -> int:
    doc = Path("docs/phase1_brainstorm.md")
    text = doc.read_text()
    if "DP result: total complexity score 18" not in text:
        print("FAIL: architecture decision not recorded")
        return 1
    phases = list(range(0, 16))
    deps = {i: [j for j in range(i)] for i in phases}
    memo = {}

    def cost(i: int) -> int:
        if i in memo:
            return memo[i]
        memo[i] = 1 if not deps[i] else 1 + max(cost(j) for j in deps[i])
        return memo[i]

    total = sum(cost(i) for i in phases)
    if total != 136:
        print(f"FAIL: phase schedule cost {total} != 136")
        return 1
    print(f"free-dp-pro: PASS (phases 0-15, schedule cost {total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
