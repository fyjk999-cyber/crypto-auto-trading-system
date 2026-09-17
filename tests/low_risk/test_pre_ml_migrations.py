"""PRE-ML convergence migration integrity tests.

The convergence merge joins the Growth/memory migration line and the
Hedge/PositionLeg migration line. They must resolve to exactly one head and a
clean upgrade from base must create both table families.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_pre_ml_convergence_has_single_migration_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert list(script.get_heads()) == ["0043_research_scope"]


def test_clean_upgrade_creates_growth_and_position_leg_tables(tmp_path) -> None:
    db_path = tmp_path / "pre_ml_convergence.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        tables = set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {
        "position_legs",
        "position_leg_orders",
        "position_leg_fills",
        "growth_memory_speeds",
        "growth_generalized_knowledge",
        "growth_memory_versions",
    } <= tables
