"""SPAC requirement coverage checks used by the agent-project-test gate."""

from pathlib import Path

from sqlalchemy import UniqueConstraint

from crypto_trader.config import Settings
from crypto_trader.persistence.models import Base

ROOT = Path(__file__).resolve().parents[2]


def test_required_package_boundaries_exist():
    required = {
        "domain",
        "market_data",
        "exchange",
        "execution",
        "order",
        "ledger",
        "portfolio",
        "risk",
        "runtime",
        "simulator",
        "reconciliation",
        "persistence",
        "observability",
        "strategy",
        "api",
    }
    for name in required:
        assert (ROOT / "src" / "crypto_trader" / name).is_dir(), name


def test_required_database_tables_exist():
    required = {
        "engine_runs",
        "runtime_leases",
        "orders",
        "order_events",
        "fills",
        "trades",
        "ledger_entries",
        "accounts_projection",
        "positions_projection",
        "market_snapshots",
        "reconciliation_runs",
        "risk_decisions",
        "audit_events",
    }
    assert required.issubset(set(Base.metadata.tables.keys()))


def test_unique_id_constraints_exist():
    def columns_with_unique(table):
        cols = []
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                cols.extend(c.name for c in constraint.columns)
        cols.extend(c.name for c in table.columns if c.unique)
        return set(cols)

    assert "client_order_id" in columns_with_unique(Base.metadata.tables["orders"])
    assert "fill_id" in columns_with_unique(Base.metadata.tables["fills"])
    assert "event_id" in columns_with_unique(Base.metadata.tables["order_events"])
    assert "transaction_id" in columns_with_unique(Base.metadata.tables["ledger_transactions"])


def test_default_mode_is_paper_and_live_disabled():
    settings = Settings(_env_file=None)
    assert settings.trading_mode.value == "PAPER"
    assert settings.live_trading_enabled is False


def test_no_ashare_semantics_in_core_src():
    forbidden = ["T+1", "qfq", "涨跌停", "印花税", "100 股", "港股", "A 股", "沪深"]
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(errors="ignore")
        for token in forbidden:
            assert token not in text, f"{path} contains forbidden A-share semantics: {token}"


def test_no_kalshi_specific_semantics_in_core_src():
    forbidden = ["Kalshi", "kalshi", "event_ticker", "paper_accounts_v2", "signals_v2"]
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(errors="ignore")
        for token in forbidden:
            assert token not in text, f"{path} contains Kalshi-specific semantics: {token}"


def test_chaos_test_names_present():
    required = {
        "duplicate_client_order_id_test",
        "partial_fill_test",
        "fill_before_ack_test",
        "duplicate_fill_event_test",
        "cancel_fill_race_test",
        "submit_timeout_but_order_created_test",
        "websocket_disconnect_test",
        "websocket_sequence_gap_test",
        "orderbook_resync_test",
        "rate_limit_test",
        "exchange_5xx_test",
        "engine_restart_test",
        "ledger_replay_test",
        "ledger_balance_invariant_test",
        "decimal_precision_test",
        "dual_engine_lease_test",
        "stale_market_data_execution_block_test",
        "reconciliation_mismatch_test",
        "kill_switch_test",
        "database_integration_test",
    }
    text = (ROOT / "tests" / "chaos" / "test_chaos.py").read_text()
    for name in required:
        assert f"test_{name}(" in text, name


def test_docs_required_exist():
    for name in (
        "README.md",
        "SPAC.md",
        "HARNESS_GOAL.md",
        "docs/reference-source-baseline.md",
        "docs/SOURCE_PROVENANCE.md",
        "docs/phase1_brainstorm.md",
        "FINAL_REPORT.md",
    ):
        assert (ROOT / name).exists(), name


def test_migrations_and_ci_exist():
    assert (ROOT / "migrations" / "env.py").exists()
    assert (ROOT / ".github" / "workflows" / "ci.yml").exists()
