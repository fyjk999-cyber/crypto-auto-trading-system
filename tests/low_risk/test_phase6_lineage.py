"""Phase 6: identity lineage builder/validator."""

from __future__ import annotations

from crypto_trader.runtime.lineage import (
    LINEAGE_STAGES,
    build_lineage,
    validate_lineage,
)


def _full_values() -> dict:
    return {
        "opportunity_id": "opp-1",
        "decision_id": "dec-1",
        "position_episode_id": "ep-1",
        "leg_id": "leg-1",
        "trade_plan_version": 2,
        "intent_id": "int-1",
        "execution_id": "exec-1",
        "client_order_id": "coid-1",
        "exchange_order_id": "ex-1",
        "fill_ids": ["fill-1", "fill-2"],
    }


def test_complete_lineage_covers_all_stages() -> None:
    chain = build_lineage(**_full_values())
    result = validate_lineage(chain)
    assert result["complete"] is True
    assert result["trade_complete"] is True
    assert result["missing"] == []
    assert result["stages"] == list(LINEAGE_STAGES)
    assert result["authority"] == "LINEAGE_ONLY"
    assert result["is_order"] is False


def test_missing_fill_and_exchange_ids_are_reported() -> None:
    values = _full_values()
    values["fill_ids"] = []
    values["exchange_order_id"] = None
    chain = build_lineage(**values)
    result = validate_lineage(chain)
    assert result["complete"] is False
    assert result["trade_complete"] is False
    assert set(result["missing"]) == {"exchange_order_id", "fill_ids"}


def test_decision_without_opportunity_is_trade_complete_if_trade_links_exist() -> None:
    values = _full_values()
    values.pop("opportunity_id")
    values.pop("position_episode_id")
    values.pop("leg_id")
    result = validate_lineage(build_lineage(**values))
    assert result["complete"] is False
    assert result["trade_complete"] is True
    assert set(result["missing"]) == {"opportunity_id", "position_episode_id", "leg_id"}


def test_unexpected_keys_are_surfaced_without_breaking_the_chain() -> None:
    values = _full_values()
    values["rogue_field"] = "x"
    result = validate_lineage(build_lineage(**values))
    assert result["unexpected"] == ["rogue_field"]
    assert result["trade_complete"] is True


def test_lineage_from_order_maps_metadata_with_fallbacks() -> None:
    from crypto_trader.runtime.lineage import lineage_from_order

    chain = lineage_from_order(
        metadata={
            "decision_id": "dec-1",
            "entry_decision_id": "entry-1",
            "leg_id": "leg-1",
            "plan_version": 2,
            "candidate_source": "market_observer",
        },
        client_order_id="coid-1",
        exchange_order_id="ex-1",
        fill_id="fill-1",
    )
    values = chain.values
    assert values["decision_id"] == "dec-1"
    assert values["opportunity_id"] == "market_observer"
    assert values["leg_id"] == "leg-1"
    assert values["trade_plan_version"] == 2
    assert values["intent_id"] == "coid-1"  # fallback
    assert values["execution_id"] == "ex-1"  # fallback
    assert values["fill_ids"] == ["fill-1"]
    assert chain.trade_complete() is True


async def test_engine_fill_settlement_emits_complete_lineage(database) -> None:
    """A factual PAPER fill must persist a complete FILL_LINEAGE audit chain."""
    import json

    from sqlalchemy import select

    from crypto_trader.persistence.models import AuditEventORM
    from tests.conftest import make_paper_engine

    engine = make_paper_engine(database, engine_tick_seconds=3600)
    engine.audit.log = engine.audit.log  # keep canonical service
    await engine.start("run-lineage-fill")
    assert await engine._strategy_context("BTCUSDT") is not None

    from tests.low_risk.test_phase4_runtime_deterministic_exit import _open_v2_position

    await _open_v2_position(engine, database)
    await engine.wait_for_event_queue()

    async with database.session_factory() as session:
        rows = (await session.execute(select(AuditEventORM))).scalars().all()
    lineage_rows = [row for row in rows if row.action == "FILL_LINEAGE"]
    assert lineage_rows, "canonical fill settlement must audit FILL_LINEAGE"
    payload = lineage_rows[-1].after_json
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload["trade_complete"] is True
    assert "client_order_id" not in payload["missing"]
    assert "fill_ids" not in payload["missing"]
    assert payload["authority"] == "LINEAGE_ONLY"
    await engine.stop()


def test_fill_lineage_issues_reports_missing_links() -> None:
    from crypto_trader.runtime.lineage_audit import fill_lineage_issues

    assert fill_lineage_issues(fill_id="f1", client_order_id="c1", exchange_order_id="e1") == []
    assert fill_lineage_issues(fill_id="f1", client_order_id=None, exchange_order_id="") == [
        "MISSING_CLIENT_ORDER_ID",
        "MISSING_EXCHANGE_ORDER_ID",
    ]


async def test_lineage_audit_flags_untracked_factual_fill(database) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from crypto_trader.persistence.models import FillORM, OrderORM
    from crypto_trader.runtime.lineage_audit import LineageCoverageAuditor

    now = datetime.now(UTC)
    async with database.session_factory() as session:
        session.add(
            OrderORM(
                internal_order_id="ord-audit-1",
                client_order_id="coid-audit-1",
                symbol="BTCUSDT",
                side="BUY",
                order_type="LIMIT",
                time_in_force="GTC",
                quantity=Decimal("0.1"),
                status="FILLED",
                trading_mode="PAPER",
                strategy_id="live_llm",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            FillORM(
                fill_id="fill-audit-tracked",
                order_id="ord-audit-1",
                client_order_id="coid-audit-1",
                exchange_order_id="ex-audit-1",
                symbol="BTCUSDT",
                side="BUY",
                price=Decimal("100"),
                quantity=Decimal("0.1"),
                timestamp=now,
            )
        )
        session.add(
            FillORM(
                fill_id="fill-audit-untracked",
                order_id="ord-audit-1",
                client_order_id=None,
                exchange_order_id=None,
                symbol="BTCUSDT",
                side="BUY",
                price=Decimal("100"),
                quantity=Decimal("0.1"),
                timestamp=now,
            )
        )
        await session.commit()

    report = await LineageCoverageAuditor(database.session_factory).audit()
    assert report["fill_count"] == 2
    assert report["untracked_count"] == 1
    assert report["ok"] is False
    assert report["flag"] == "UNTRACKED_FACTUAL_FILL"
    assert report["untracked"][0]["fill_id"] == "fill-audit-untracked"
    assert report["authority"] == "RECONCILIATION_ONLY"
    assert report["is_order"] is False


async def test_recovery_flags_untracked_factual_fill(database) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from sqlalchemy import select

    from crypto_trader.persistence.models import AuditEventORM, FillORM, OrderORM
    from tests.conftest import make_paper_engine

    now = datetime.now(UTC)
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-recovery-lineage")

    async with database.session_factory() as session:
        session.add(
            OrderORM(
                internal_order_id="ord-rec-1",
                client_order_id="coid-rec-1",
                symbol="BTCUSDT",
                side="BUY",
                order_type="LIMIT",
                time_in_force="GTC",
                quantity=Decimal("0.1"),
                status="FILLED",
                trading_mode="PAPER",
                strategy_id="live_llm",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            FillORM(
                fill_id="fill-rec-untracked",
                order_id="ord-rec-1",
                client_order_id=None,
                exchange_order_id=None,
                symbol="BTCUSDT",
                side="BUY",
                price=Decimal("100"),
                quantity=Decimal("0.1"),
                timestamp=now,
            )
        )
        await session.commit()

    actions = await engine._run_recovery("run-recovery-lineage")
    assert "RECOVERY_LINEAGE_GAPS" in actions
    assert engine.health.snapshot()["components"]["factual_fill_lineage"]["ok"] is False
    async with database.session_factory() as session:
        events = [
            row.action for row in (await session.execute(select(AuditEventORM))).scalars().all()
        ]
    assert "RECOVERY_LINEAGE_GAPS" in events
    await engine.stop()


async def test_recovery_halts_on_fill_vs_portfolio_divergence(database) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from sqlalchemy import select

    from crypto_trader.persistence.models import AuditEventORM, FillORM, OrderORM
    from tests.conftest import make_paper_engine

    now = datetime.now(UTC)
    engine = make_paper_engine(database, engine_tick_seconds=3600)
    await engine.start("run-recovery-divergence")
    assert engine.reconciliation_halted is False

    async with database.session_factory() as session:
        session.add(
            OrderORM(
                internal_order_id="ord-div-1",
                client_order_id="coid-div-1",
                exchange_order_id="ex-div-1",
                symbol="CAPUSDT",
                side="SELL",
                order_type="LIMIT",
                time_in_force="GTC",
                quantity=Decimal("122"),
                status="FILLED",
                trading_mode="PAPER",
                strategy_id="live_llm",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            FillORM(
                fill_id="fill-div-1",
                order_id="ord-div-1",
                client_order_id="coid-div-1",
                exchange_order_id="ex-div-1",
                symbol="CAPUSDT",
                side="SELL",
                price=Decimal("0.05796"),
                quantity=Decimal("122"),
                timestamp=now,
            )
        )
        await session.commit()

    actions = await engine._run_recovery("run-recovery-divergence")
    assert "RECOVERY_FACTUAL_DIVERGENCE" in actions
    assert engine.reconciliation_halted is True
    assert engine.health.snapshot()["components"]["recovery_factual_state"]["ok"] is False
    async with database.session_factory() as session:
        events = [
            row.action for row in (await session.execute(select(AuditEventORM))).scalars().all()
        ]
    assert "RECOVERY_FACTUAL_DIVERGENCE" in events
    await engine.stop()
