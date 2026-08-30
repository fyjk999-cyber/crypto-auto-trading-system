"""Phase H tool-utility report CLI (advisory only; read + lesson emission).

Usage (from repo root):
  python scripts/tool_utility_report.py --window-hours 24
  python scripts/tool_utility_report.py --window-hours 24 --emit-lesson

The report (P2 CS-20260830-034530-P4-TOOL-LINEAGE) is factual: per-tool
volume/error/latency with sample sizes, decision-outcome pairing through the
durable Episode -> entry decision -> tool invocation link, factor analysis
(regime / strategy / symbol), attributable token cost, decision-evidence
change markers and an information-value comparison -- all labelled
CORRELATION_NOT_CAUSATION. Lessons are advisory evidence for the calibration
agent and the LLM context - never a trading gate and never a risk authority.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from crypto_trader.config import Settings  # noqa: E402
from crypto_trader.governance.tool_journal import ToolInvocationJournal  # noqa: E402
from crypto_trader.persistence.database import Database  # noqa: E402


async def main_async(window_hours: int, emit_lesson: bool) -> int:
    settings = Settings()
    database = Database(settings.database_url)
    journal = ToolInvocationJournal(database.session_factory)
    report = await journal.utility_report(window_hours=window_hours)
    print(json.dumps(report, indent=2, default=str))
    if emit_lesson:
        lesson_id = await journal.emit_lesson(report)
        print(json.dumps({"emitted_lesson": lesson_id}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-hours", type=int, default=24)
    parser.add_argument(
        "--emit-lesson", action="store_true",
        help="write the one advisory lesson into learning_lessons",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args.window_hours, args.emit_lesson))


if __name__ == "__main__":
    raise SystemExit(main())
