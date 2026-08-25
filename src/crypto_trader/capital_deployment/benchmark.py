"""LLM fund manager vs legacy benchmark comparison."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BenchmarkRow:
    timestamp: str
    symbol: str
    legacy_decision: str
    llm_decision: str
    actual_result: str
    classification: str  # LEGACY_CORRECT | LLM_CORRECT | BOTH_CORRECT | BOTH_WRONG | INCONCLUSIVE


class LegacyBenchmarkEngine:
    def compare(self, rows: list[BenchmarkRow]) -> dict:
        legacy_correct = 0
        llm_correct = 0
        both = 0
        both_wrong = 0
        inconclusive = 0
        for row in rows:
            if row.actual_result == "INCONCLUSIVE":
                row.classification = "INCONCLUSIVE"
                inconclusive += 1
            else:
                legacy_ok = row.legacy_decision == row.actual_result
                llm_ok = row.llm_decision == row.actual_result
                if legacy_ok and llm_ok:
                    row.classification = "BOTH_CORRECT"
                    both += 1
                elif legacy_ok:
                    row.classification = "LEGACY_CORRECT"
                    legacy_correct += 1
                elif llm_ok:
                    row.classification = "LLM_CORRECT"
                    llm_correct += 1
                else:
                    row.classification = "BOTH_WRONG"
                    both_wrong += 1
        total = len(rows) or 1
        return {
            "legacy_win_rate": (legacy_correct + both) / total,
            "llm_win_rate": (llm_correct + both) / total,
            "legacy_correct": legacy_correct,
            "llm_correct": llm_correct,
            "both_correct": both,
            "both_wrong": both_wrong,
            "inconclusive": inconclusive,
        }
