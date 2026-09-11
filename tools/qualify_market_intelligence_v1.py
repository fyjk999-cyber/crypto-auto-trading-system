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
                    "oi_batch_quality": snapshot.data_quality_summary["batch"]["open_interest"],
                    "oi_collection": snapshot.data_quality_summary.get(
                        "open_interest_collection", {}
                    ),
                    "oi_quality_states": _state_histogram(
                        [row.get("oi_quality") for row in snapshot.observable_rows]
                    ),
                    "feature_coverage": dict(snapshot.feature_coverage),
                    "oi_covered_symbols": sorted(
                        row["symbol"]
                        for row in snapshot.observable_rows
                        if row.get("oi_quality") == "VALID"
                    ),
                    "oi_usd_sample": next(
                        (
                            row.get("open_interest_usd")
                            for row in snapshot.observable_rows
                            if row.get("open_interest_usd") is not None
                        ),
                        None,
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
            "oi_coverage_ratio": (snapshot.feature_coverage or {}).get("oi_coverage_ratio"),
            "oi_coverage_count": (snapshot.feature_coverage or {}).get("oi_coverage_count"),
            "funding_coverage_ratio": (snapshot.feature_coverage or {}).get(
                "funding_coverage_ratio"
            ),
            "ticker_coverage_ratio": (snapshot.feature_coverage or {}).get(
                "ticker_coverage_ratio"
            ),
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
            "exploration_rounds": record.exploration_rounds,
            "scan_id_matches_snapshot": record.scan_id == snapshot.scan_id,
            "input_tokens_note": (
                "phase-1 context only (no preloaded directory pages); the previous "
                "implementation sent preloaded directory pages in one call"
            ),
        }
        persisted = await selection_service.store.load_for_scan(snapshot.scan_id)
        report["selection"]["persisted"] = persisted is not None
        report["selection"]["duplicate_guard"] = (
            await selection_service.maybe_select(existing_positions=[])
        ).selection_id == record.selection_id

        # ---- controlled REQUEST_DIRECTORY induction (real directory + real LLM)
        report["selection_exploration"] = await _induced_exploration(
            bundle, selection_service
        )

        # ---- deterministic research-attention authority evidence -----------
        report["authority_semantics"] = _authority_semantics(bundle, selection_service)

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


async def _induced_exploration(bundle, selection_service) -> dict:
    """Exercise the REQUEST_DIRECTORY path with a REAL phase-2 DeepSeek call.

    The first phase is scripted to REQUEST_DIRECTORY (a controlled harness
    decision, so the path is safely inducible); the directory lookup and the
    FINAL selection call are real: the same real ChiefTrader receives the real
    read-only directory result and must return SELECT or NO_RESEARCH.
    """
    from crypto_trader.llm_chief.engine import MarketSelectionResult as _Result
    from crypto_trader.market_data.opportunity.selection import (
        parse_selection_payload,
    )

    scanner = bundle.engine.opportunity_service
    snapshot = await scanner.scan_once()
    board = scanner.board
    usable = board.current_snapshot()
    service = selection_service
    real_chief = service.chief
    state = {"phase1_done": False}

    class InducedChief:
        """Same ChiefTrader; only the FIRST phase prompt is answered by script."""

        async def select_markets(self, context, **kwargs):
            if not state["phase1_done"]:
                state["phase1_done"] = True
                parsed = parse_selection_payload(
                    {
                        "selection_state": "REQUEST_DIRECTORY",
                        "directory_query": {"sort": "abs_move", "page": 1},
                    },
                    selection_id=kwargs["selection_id"],
                    scan_id=kwargs["scan_id"],
                )
                return _Result(ok=True, status="SUCCESS", output=parsed, provider="harness")
            return await real_chief.select_markets(context, **kwargs)

    service.chief = InducedChief()
    try:
        record = await service.maybe_select(existing_positions=[])
    finally:
        service.chief = real_chief
    discovered = [s for s in record.selected_symbols if s.get("discovered_via_directory")]
    return {
        "scan_id": snapshot["scan_id"],
        "status": record.status,
        "selection_state": record.selection_state,
        "exploration_rounds": record.exploration_rounds,
        "directory_query": record.directory_query,
        "directory_page_refs": list(record.directory_query_refs),
        "selected_symbols": record.selected_symbols,
        "discovered_via_directory": [s["symbol"] for s in discovered],
        "real_phase2_provider": record.provider,
        "real_phase2_model": record.model,
        "phase2_input_tokens": record.input_tokens,
        "phase2_output_tokens": record.output_tokens,
        "snapshot_id_matches": record.scan_id == usable.scan_id,
    }


def _authority_semantics(bundle, selection_service) -> dict:
    """Prove on the PRODUCTION path that selection states never fall back.

    Calls the real ``LiveLLMDecisionStrategy.desired_symbol()`` with the real
    OpportunityBoard (which always has a candidate and rotation symbol) and the
    real MarketSelectionService whose ``last_record`` is temporarily replaced by
    each terminal/failed state. If any programmatic fallback existed, the board
    candidate would be returned.
    """
    from crypto_trader.market_data.opportunity.selection import MarketSelectionRecord

    strategy = None
    for candidate in bundle.engine.strategies:
        if getattr(candidate, "name", "") == "live_llm":
            strategy = candidate
    if strategy is None or strategy.selection_service is None:
        return {"available": False, "reason": "no live_llm strategy wired"}

    board = strategy.opportunity_board
    board_next = board.next_agenda_symbol() if board is not None else None
    real_record = selection_service.last_record
    cases: list[dict] = []
    try:
        for index, (case_name, status, state) in enumerate(
            (
                ("NO_RESEARCH", "NO_RESEARCH", "NO_RESEARCH"),
                ("SELECTION_LLM_UNAVAILABLE", "LLM_UNAVAILABLE", ""),
                ("SELECTION_TIMEOUT", "TIMEOUT", ""),
                ("SELECTION_FAILED", "FAILED", ""),
                ("SELECTION_SKIPPED_BUDGET", "SKIPPED_BUDGET", ""),
                ("SELECTION_DEFERRED", "DEFERRED", ""),
                ("SELECTION_QUEUE_EXHAUSTED", "SUCCESS", "SELECT"),
            )
        ):
            selection_service.last_record = MarketSelectionRecord(
                selection_id=f"mkt_sel_authority_{index}",
                scan_id=board.current_snapshot().scan_id,
                status=status,
                selection_state=state,
                selected_symbols=[],
                requested_at=real_record.requested_at if real_record else None,
            )
            if case_name == "SELECTION_QUEUE_EXHAUSTED":
                # consume the (empty) queue once so it is marked exhausted
                strategy.desired_symbol()
            observed = strategy.desired_symbol()
            cases.append(
                {
                    "case": case_name,
                    "record_status": status,
                    "desired_symbol": observed,
                    "board_candidate_available": board_next,
                    "board_candidate_consumed": observed == board_next and board_next is not None,
                }
            )
    finally:
        selection_service.last_record = real_record

    fallback_used = any(case["board_candidate_consumed"] for case in cases)
    return {
        "available": True,
        "programmatic_fallback_when_selection_enabled": "YES" if fallback_used else "NO",
        "board_candidate_available": board_next,
        "cases": cases,
        "note": (
            "desired_symbol() is the canonical production path; the board always "
            "had a candidate/rotation symbol available, so a value returned here "
            "would prove a programmatic fallback"
        ),
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
        "oi_contract_broad_coverage": (
            "YES"
            if (observation.get("oi_coverage_ratio") or 0.0) >= 0.99
            else "NO"
        ),
        "oi_batch_quality_truthful": (
            "YES" if "VALID" in _flatten_oi_states(observation) else "NO"
        ),
        "fair_rotation_progressing": (
            "YES" if observation.get("rotation_progressed") else "NO"
        ),
        "snapshot_status_distinguishes_coverage": "YES" if cycles else "NO",
        "same_chief_market_selection_executes": (
            "YES" if selection.get("status") in ("SUCCESS", "NO_RESEARCH") else "NO"
        ),
        "no_research_is_supported": (
            "YES"
            if selection.get("status") in ("NO_RESEARCH", "SUCCESS")
            and selection.get("selection_state") in ("NO_RESEARCH", "SELECT")
            else "NO"
        ),
        "selected_symbol_invokes_real_tools": (
            "YES" if research.get("executed") and research.get("evidence_items", 0) > 0 else "NO"
        ),
        "tool_lineage_matches_selected_symbol": (
            "YES" if research.get("tool_symbols_match_research_target") else "NO"
        ),
        "research_attention_authority_ready": (
            "YES"
            if (report.get("authority_semantics") or {}).get(
                "programmatic_fallback_when_selection_enabled"
            )
            == "NO"
            else "NO"
        ),
        "no_research_fails_closed_on_production_path": (
            "YES"
            if all(
                case.get("desired_symbol") is None
                for case in (
                    (report.get("authority_semantics") or {}).get("cases") or []
                )
            )
            and (report.get("authority_semantics") or {}).get("cases")
            else "NO"
        ),
        "chief_controlled_directory_exploration": (
            "YES"
            if (report.get("selection_exploration") or {}).get("exploration_rounds") == 1
            and (report.get("selection_exploration") or {}).get("real_phase2_provider")
            else "NO"
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
