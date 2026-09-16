"""M10: final ML authority and migration-head acceptance."""

from __future__ import annotations

import inspect

from alembic.config import Config
from alembic.script import ScriptDirectory

from crypto_trader import (
    ml_artifacts,
    ml_dataset,
    ml_forward,
    ml_lifecycle,
    ml_meta,
    ml_orchestrator,
    ml_trainer,
)
from crypto_trader.factors.expert import engine as expert_engine
from crypto_trader.factors.expert import models as expert_models

ORDER_AUTHORITY_TOKENS = (
    "ExecutionAuthority",
    "OrderManager",
    "submit_order",
    "process_signal",
    "SignalIntent",
)


def test_ml_modules_have_no_order_authority_tokens() -> None:
    for module in (
        ml_artifacts,
        ml_dataset,
        ml_forward,
        ml_lifecycle,
        ml_meta,
        ml_orchestrator,
        ml_trainer,
        expert_engine,
        expert_models,
    ):
        source = inspect.getsource(module)
        for token in ORDER_AUTHORITY_TOKENS:
            assert token not in source, f"{module.__name__} must not reference {token}"


def test_ml_outputs_are_learning_only_not_orders() -> None:
    assert ml_forward.ForwardPredictionStore.authority == "LEARNING_ONLY"
    assert ml_forward.ForwardPredictionStore.is_order is False
    from crypto_trader.factors.expert.engine import ExpertEvidencePackage

    assert "not_an_order" in inspect.getsource(ExpertEvidencePackage.as_dict)
    status = ml_orchestrator.MLOrchestrator.__dict__.get("snapshot")
    assert status is not None
    assert "LEARNING_ONLY" in inspect.getsource(status)


def test_ml_migration_head_is_single_and_forward_schema_present() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = list(script.get_heads())
    assert heads == ["0034_ml_forward_model21_lineage"]
    revision = script.get_revision("0034_ml_forward_model21_lineage")
    assert revision is not None
