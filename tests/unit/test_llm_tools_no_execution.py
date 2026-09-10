import inspect

from crypto_trader.llm.tools import registry


def test_llm_tool_registry_has_no_execution_authority():
    source = inspect.getsource(registry)
    for forbidden in (
        "OrderManager",
        "TradePlanService",
        "ExecutionAuthority",
        "RiskEngine",
        "place_order",
        "submit_order",
    ):
        assert forbidden not in source, f"tool registry must not reference {forbidden}"
