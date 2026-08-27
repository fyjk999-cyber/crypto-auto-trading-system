"""Time-compressed closed-loop smoke (paper). Not a substitute for 24h soak."""
import asyncio
import os
import tempfile
from decimal import Decimal

from crypto_trader.config import Settings
from crypto_trader.decision_replay.evidence import DecisionEvidence
from crypto_trader.evolution.daily.pipeline import DailyReviewPipeline
from crypto_trader.evolution.hierarchical.engine import HierarchicalLearningEngine
from crypto_trader.evolution.promotion.coordinator import SafePromotionCoordinator
from crypto_trader.evolution.promotion.contracts import TradingRelease, UpgradeReadinessSnapshot
from crypto_trader.runtime.bootstrap import build_system
from datetime import UTC, datetime


async def main():
    db_path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    os.unlink(db_path)
    settings = Settings(
        _env_file=None, app_env="test", trading_mode="PAPER",
        live_trading_enabled=False, database_url=f"sqlite+aiosqlite:///{db_path}",
        auto_start_runtime=False, paper_mode="PAPER_SYNTHETIC",
        paper_initial_equity="100000", engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600, run_lease_renew_interval_seconds=3600)
    bundle = await build_system(settings)
    await bundle.engine.start()
    # evidence write (immutable trading facts)
    bundle.engine.ai_position_bridge.decision_history.append(
        {"symbol": "BTCUSDT", "action": "HOLD", "confidence": 0.6})
    # daily review
    daily = DailyReviewPipeline().run(
        review_id="r-daily", period_id="2026-08-25",
        starts_at="2026-08-25T00:00:00+00:00",
        ends_at="2026-08-25T23:59:59.999999+00:00",
        decisions=[{"decision_id": "d1", "trade": True, "decision_quality": "GOOD",
                    "outcome_quality": "GOOD"}],
        triggered_at="2026-08-26T00:05:00+00:00")
    # hierarchical
    engine = HierarchicalLearningEngine()
    weekly = engine.weekly_review(
        review_id="r-weekly", period_id="2026-W35", starts_at="", ends_at="",
        daily_reviews=[daily.to_dict()])
    # promotion dry-run
    coordinator = SafePromotionCoordinator()
    snapshot = UpgradeReadinessSnapshot(
        timestamp_utc=datetime.now(UTC).isoformat(), candidate_id="c1",
        champion_version="v1", open_positions=0, open_orders=0,
        in_flight_orders=0, pending_execution=0, recent_entry_count=0,
        market_volatility_state="NORMAL", spread_state="NORMAL",
        liquidity_state="NORMAL", market_data_health="HEALTHY",
        exchange_health="HEALTHY", reconciliation_health="HEALTHY",
        ledger_health="HEALTHY", portfolio_health="HEALTHY",
        risk_health="HEALTHY", kill_switch_state="OFF",
        runtime_lease_health="HEALTHY", critical_incidents=0)
    release = TradingRelease(
        release_id="r1", strategy_version="s2", factor_set_version="f2",
        prompt_version="p2", model_routing_version="m2",
        code_commit="abc", config_hash="cfg", parent_release_id="r0",
        candidate_id="c1", promotion_id="p1")
    promotion = coordinator.promote(
        promotion_id="p1", candidate_id="c1", certified=True,
        snapshot=snapshot, target_release=release, health_pass=True, smoke_pass=True)
    print("SOAK_SMOKE", "daily", daily.status, "weekly_period", weekly.period_id,
          "promotion", promotion.status)
    await bundle.engine.stop()
    await bundle.database.close()
    print("SOAK_SMOKE_OK")


if __name__ == "__main__":
    asyncio.run(main())
