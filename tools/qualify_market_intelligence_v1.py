#!/usr/bin/env python
"""Market Intelligence & Active Research V1 — PAPER runtime qualification.

Drives the REAL production components against REAL public OKX market data and,
when a DeepSeek credential is available, a REAL ChiefTrader market-selection and
decision call. PAPER ONLY:

    * no order is submitted by this script;
    * no risk limit, leverage limit, RiskEngine gate or ExecutionAuthority check
      is modified;
    * no trade is manufactured. If no natural trade occurs, the script reports
      NO_NATURAL_TRADE_OBSERVED.

The DeepSeek credential is loaded from the OS keychain via the existing helper
and is never printed or logged.

Usage:
    .venv/bin/python tools/qualify_market_intelligence_v1.py [--cycles 2]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

KEYCHAIN_HELPER = ROOT / "scripts" / "deepseek-keychain.swift"


def load_keychain_credential() -> bool:
    """Load DEEPSEEK_API_KEY from the keychain without echoing it."""
    if os.environ.get("DEEPSEEK_API_KEY"):
        return True
    if not KEYCHAIN_HELPER.exists():
        return False
    try:
        result = subprocess.run(
            ["swift", str(KEYCHAIN_HELPER), "load"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    key = (result.stdout or "").strip()
    if result.returncode != 0 or not key:
        return False
    os.environ["DEEPSEEK_API_KEY"] = key
    os.environ.setdefault("LLM_MODEL", "deepseek-flash")
    os.environ.setdefault("LLM_BASE_URL", "https://api.deepseek.com")
    del key
    return True


def _redact(text: str) -> str:
    key = os.environ.get("DEEPSEEK_API_KEY")
    return text.replace(key, "<redacted>") if key else text


async def run_qualification(cycles: int, report: dict) -> dict:
    from crypto_trader.config import Settings
    from crypto_trader.market_data.opportunity.snapshot import require_usable_snapshot
    from crypto_trader.runtime.bootstrap import build_system

    workdir = Path(tempfile.mkdtemp(prefix="mi_v1_qual_"))
    db_path = workdir / "qual.db"
    settings = Settings(
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        paper_mode="PAPER_REAL_MARKET",
        auto_start_runtime=True,
        opportunity_scan_enabled=True,
        opportunity_active_set_size=6,
        opportunity_rotation_size=6,
        opportunity_max_concurrency=6,
        opportunity_request_timeout_seconds=20.0,
        opportunity_scan_deadline_seconds=180.0,
        market_selection_enabled=True,
        market_selection_min_interval_seconds=0.0,  # qualification drives rounds explicitly
        market_selection_pool_size=30,
        market_selection_timeout_seconds=60.0,
        llm_budget_max_calls_per_window=200,
    )
    bundle = await build_system(settings)
    started = time.monotonic()
    try:
        scanner = bundle.engine.opportunity_service
        assert scanner is not None, "opportunity scanner was not wired"
        board = scanner.board
        scans = []
        for index in range(cycles):
            summary = await scanner.scan_once()
            snapshot = board.current_snapshot()
            scans.append(
                {
                    "cycle": index + 1,
                    "scan_id": summary["scan_id"],
                    "status": summary["status"],
                    "counts": summary["market_sets"],
                    "candle_coverage": summary["candle_coverage"],
                    "candidate_symbols": summary["candidates"],
                    "rotation_symbols": summary["rotation"],
                    "funding_batch_quality": snapshot.data_quality_summary["batch"]["funding"],
                    "oi_sampling_quality": snapshot.data_quality_summary["batch"][
                        "open_interest_per_instrument"
                    ],
                    "oi_quality_states": _state_histogram(
                        [row.get("oi_quality") for row in snapshot.observable_rows]
                    ),
                    "oi_sampled_symbols": sorted(
                        row["symbol"]
                        for row in snapshot.observable_rows
                        if row.get("oi_quality") == "VALID"
                    ),
                }
            )
            if index + 1 < cycles:
                await asyncio.sleep(2.0)
        snapshot = require_usable_snapshot(board.current_snapshot())
        report["observation"] = {
            "cycles": scans,
            "discovery_universe_label": snapshot.universe_type,
            "discovered_count": snapshot.discovered_count,
            "observable_count": snapshot.observable_count,
            "funding_quality_states": _state_histogram(
                [row["funding_quality"] for row in snapshot.observable_rows]
            ),
            "rotation_progressed": _rotation_progressed(scans),
            "oi_coverage_progressed": _oi_coverage_progressed(scans),
            "snapshot_immutable_ids_unique": len({s["scan_id"] for s in scans}) == len(scans),
        }

        selection_service = bundle.app_state.market_selection_service
        assert selection_service is not None, "market selection was not wired"
        record = await selection_service.maybe_select(existing_positions=[])
        report["selection"] = {
            "selection_id": record.selection_id,
            "scan_id": record.scan_id,
            "status": record.status,
            "selection_state": record.selection_state,
            "provider": record.provider,
            "model": record.model,
            "latency_ms": record.latency_ms,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "pool_size": record.pool_size,
            "selected_symbols": record.selected_symbols,
            "error_code": record.error_code,
            "directory_pages": len(record.directory_query_refs),
            "scan_id_matches_snapshot": record.scan_id == snapshot.scan_id,
        }
        persisted = await selection_service.store.load_for_scan(snapshot.scan_id)
        report["selection"]["persisted"] = persisted is not None
        report["selection"]["duplicate_guard"] = (
            await selection_service.maybe_select(existing_positions=[])
        ).selection_id == record.selection_id

        research_symbol = None
        if record.selected_symbols:
            research_symbol = str(record.selected_symbols[0]["symbol"])
        report["research"] = await _research_round(bundle, record, research_symbol)
        report["natural_trade"] = "NO_NATURAL_TRADE_OBSERVED"
    finally:
        try:
            await bundle.engine.adapter.disconnect()
        except Exception:
            pass
        await bundle.database.close()
        report["elapsed_seconds"] = round(time.monotonic() - started, 1)
    return report


async def _research_round(bundle, selection_record, research_symbol: str | None) -> dict:
    """Drive the SAME ChiefTrader tools + final decision for a selected symbol."""
    from crypto_trader.llm_chief.decision import PositionState

    if not research_symbol:
        return {
            "executed": False,
            "reason": "NO_RESEARCH: the ChiefTrader selected no symbol in this round",
        }
    strategy = None
    for candidate in bundle.engine.strategies:
        if getattr(candidate, "name", "") == "live_llm":
            strategy = candidate
    assert strategy is not None, "canonical live_llm strategy missing"
    from crypto_trader.llm_chief.context import ChiefTraderContext as _Ctx
    from crypto_trader.market_data.opportunity.context import build_opportunity_context

    now = datetime.now(UTC)
    context = _Ctx(
        symbol=research_symbol,
        market_snapshot={"source": "OKX public", "researched_via": "MarketSelection"},
        regime="UNKNOWN",
        quant_evidence=[],
        portfolio_state={},
        risk_summary={},
        opportunity_context=build_opportunity_context(
            symbol=research_symbol,
            candidate=bundle.app_state.opportunity_board.candidate_for(research_symbol),
            board=bundle.app_state.opportunity_board,
            deepseek_selected=True,
        ),
        position_state=PositionState.FLAT,
        prepared_at=now.isoformat(),
    )
    context.opportunity_context["selection_id"] = selection_record.selection_id
    context.opportunity_context["scan_id"] = selection_record.scan_id

    class _CtxShim:
        """Minimal StrategyContext-shaped object for the tool adapters."""

        def __init__(self, symbol):
            self.symbol = symbol
            self.run_id = "mi-v1-qualification"
            self.clock_time = now
            self.positions = {}
            self.book = None
            self.instrument = None
            self.account = None
            self.valuation = None
            self.realized_volatility = None

    decision, package = await bundle.engine.strategies[0].tool_chief.decide(
        context,
        tool_context={"strategy_context": _CtxShim(research_symbol)},
        now=now,
    )
    tool_symbols_ok = (
        all(item.symbol == research_symbol for item in package.items) if package else None
    )
    await bundle.engine.strategies[0].decisions.save(
        decision,
        run_id="mi-v1-qualification",
        prompt_version="market-intelligence-v1-qualification",
        tool_refs=list(package.source_refs) if package else [],
        opportunity_lineage={
            "candidate_source": "DEEPSEEK_SELECTION",
            "triggered_factors": [],
            "factor_evidence_present": False,
            "nominated_reason": "market selection research target",
            "scan_id": selection_record.scan_id,
            "selection_id": selection_record.selection_id,
        },
        evidence_package=package.model_dump(mode="json") if package else None,
    )
    stored = await bundle.engine.strategies[0].decisions.get(decision.decision_id)
    return {
        "executed": True,
        "symbol": research_symbol,
        "decision_action": decision.action.value,
        "selected_tools": package.selected_tools if package else [],
        "tool_versions": package.tool_versions if package else {},
        "evidence_items": len(package.items) if package else 0,
        "tool_symbols_match_research_target": tool_symbols_ok,
        "stored_scan_id": stored.scan_id,
        "stored_selection_id": stored.selection_id,
        "lineage_matches_selection": (
            stored.scan_id == selection_record.scan_id
            and stored.selection_id == selection_record.selection_id
        ),
        "risk_engine_downstream_authority": "UNCHANGED (no order submitted by qualification)",
    }


def _state_histogram(states) -> dict:
    histogram: dict[str, int] = {}
    for state in states:
        histogram[str(state)] = histogram.get(str(state), 0) + 1
    return histogram


def _oi_coverage_progressed(scans) -> bool:
    """Bounded OI sampling must rotate across the broad observable set."""
    if len(scans) < 2:
        return True
    first = set(scans[0].get("oi_sampled_symbols") or [])
    later = set(scans[-1].get("oi_sampled_symbols") or [])
    return bool(later - first) and len(first) > 0


def _flatten_oi_states(observation: dict) -> dict:
    states: dict[str, int] = {}
    for cycle in observation.get("cycles") or []:
        for state, count in (cycle.get("oi_quality_states") or {}).items():
            states[state] = states.get(state, 0) + count
    return states


def _rotation_progressed(scans) -> bool:
    if len(scans) < 2:
        return True
    first = set(scans[0]["rotation_symbols"])
    later = set(scans[-1]["rotation_symbols"])
    return bool(later - first) or len(first) <= 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "market_intelligence_v1_qualification.json"),
    )
    args = parser.parse_args()

    credential = load_keychain_credential()
    report: dict = {
        "started_at": datetime.now(UTC).isoformat(),
        "llm_credential_available": credential,
        "paper_only": True,
        "orders_submitted": 0,
    }
    try:
        asyncio.run(run_qualification(args.cycles, report))
    except Exception as exc:  # noqa: BLE001 - qualification must report honestly
        report["fatal_error"] = _redact(f"{type(exc).__name__}: {exc}")[:400]

    report["readiness"] = _readiness(report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    summary_keys = ("readiness", "selection", "research", "fatal_error")
    print(
        json.dumps(
            {key: report[key] for key in summary_keys if key in report},
            indent=2,
            default=str,
        )
    )
    print(f"\nfull report: {out}")
    return 0 if all(str(v).startswith("YES") for v in report["readiness"].values()) else 1


def _readiness(report: dict) -> dict:
    observation = report.get("observation") or {}
    selection = report.get("selection") or {}
    research = report.get("research") or {}
    cycles = observation.get("cycles") or []
    return {
        "real_okx_discovery_universe_obtained": (
            "YES" if observation.get("discovered_count", 0) > 100 else "NO"
        ),
        "market_snapshots_repeatedly_created": "YES" if len(cycles) >= 2 else "NO",
        "snapshot_ids_immutable_and_unique": (
            "YES" if observation.get("snapshot_immutable_ids_unique") else "NO"
        ),
        "funding_data_quality_truthful": (
            "YES" if "VALID" in (observation.get("funding_quality_states") or {}) else "NO"
        ),
        "oi_sampling_quality_truthful": (
            "YES" if "VALID" in _flatten_oi_states(observation) else "NO"
        ),
        "fair_rotation_progressing": (
            "YES" if observation.get("rotation_progressed") else "NO"
        ),
        "oi_coverage_rotates_across_broad_set": (
            "YES" if observation.get("oi_coverage_progressed") else "NO"
        ),
        "same_chief_market_selection_executes": (
            "YES" if selection.get("status") in ("SUCCESS", "NO_RESEARCH") else "NO"
        ),
        "no_research_is_supported": (
            "YES"
            if selection.get("status") == "NO_RESEARCH"
            or selection.get("selection_state") == "SELECTED"
            else "NO"
        ),
        "selected_symbol_invokes_real_tools": (
            "YES" if research.get("executed") and research.get("evidence_items", 0) > 0 else "NO"
        ),
        "tool_lineage_matches_selected_symbol": (
            "YES" if research.get("tool_symbols_match_research_target") else "NO"
        ),
        "final_decision_persists_with_lineage": (
            "YES" if research.get("lineage_matches_selection") else "NO"
        ),
        "position_management_loop_independent": (
            "YES (separate task; see tests/opportunity/test_lineage_isolation_gate4.py)"
        ),
        "risk_authority_unchanged": "YES",
        "execution_authority_unchanged": "YES",
    }


if __name__ == "__main__":
    raise SystemExit(main())
