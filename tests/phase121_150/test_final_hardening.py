from datetime import UTC, datetime
from pathlib import Path

from crypto_trader.llm_chief.temporal_guard import TemporalDataGuard
from crypto_trader.persistence.models import Base


def test_ai_memory_tables_exist_in_metadata():
    table_names = set(Base.metadata.tables.keys())
    for name in (
        "llm_strategy_cards",
        "ai_trade_episodes",
        "ai_trade_reviews",
        "ai_market_patterns",
        "ai_coin_profiles",
        "ai_compressed_experience",
        "shadow_campaigns",
        "capital_allocations",
    ):
        assert name in table_names, f"missing {name}"


def test_alembic_migration_file_exists_for_ai_memory():
    migration = Path("migrations/versions/0003_ai_memory_and_shadow_tables.py")
    assert migration.exists()
    content = migration.read_text()
    assert "llm_strategy_cards" in content
    assert "shadow_campaigns" in content
    assert "capital_allocations" in content


def test_temporal_guard_blocks_future_leakage():
    t = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
    guard = TemporalDataGuard(t)
    result = guard.validate(
        [
            {"id": "ep1", "timestamp": "2026-08-24T00:00:00+00:00"},
            {"id": "ep2", "timestamp": "2026-08-26T00:00:00+00:00"},
        ]
    )
    assert result.allowed is False
    assert "ep2" in result.blocked_objects
    ok = guard.validate([{"id": "ep1", "timestamp": "2026-08-25T11:59:00+00:00"}])
    assert ok.allowed is True


def test_context_budget_manager():
    from crypto_trader.llm_chief.engines import ContextBudgetManager

    budget = ContextBudgetManager(normal_limit=5000, deep_limit=12000)
    assert budget.fit(4000) is True
    assert budget.fit(6000) is False
    assert budget.fit(11000, deep_research=True) is True


def test_incident_and_safe_mode_determinism():
    from crypto_trader.capital_deployment.emergency import EmergencyDrillRunner

    runner = EmergencyDrillRunner()
    assert runner.ACTION_MAP["stale_market_data"] == "NO_NEW_TRADES"
    assert runner.ACTION_MAP["database_failure"] == "SAFE_MODE"
    assert runner.ACTION_MAP["process_crash"] == "KILL_SWITCH"
