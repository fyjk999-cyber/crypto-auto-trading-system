import inspect

from crypto_trader.validation import ablation, counterexample, oos, time_split


def test_validation_modules_have_no_live_execution_authority():
    forbidden = (
        "OrderManager",
        "TradePlanService",
        "ExecutionAuthority",
        "RiskEngine",
    )
    for module in (ablation, counterexample, oos, time_split):
        source = inspect.getsource(module)
        for token in forbidden:
            assert token not in source, f"{module.__name__} imports live authority {token}"
