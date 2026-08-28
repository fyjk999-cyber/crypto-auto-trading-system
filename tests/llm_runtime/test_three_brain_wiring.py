from crypto_trader.config import Settings
from crypto_trader.evolution.gateways.research_gateway import ResearchGateway
from crypto_trader.governance.memory_persistence import MemoryPersistence
from crypto_trader.governance.scheduler import DailyLLMRetryableError, DailyReviewScheduler
from crypto_trader.llm_runtime.contracts import LLMErrorCode, LLMResponse
from crypto_trader.runtime.bootstrap import build_system
from crypto_trader.runtime.chief_trader_strategy import ChiefTraderStrategyAdapter


class UnavailableGateway:
    async def invoke(self, request, *_args):
        return LLMResponse(
            invocation_id="unavailable",
            ok=False,
            route=request.route,
            error_code=LLMErrorCode.NOT_CONFIGURED,
        )


async def test_canonical_bootstrap_wires_one_gateway_into_exactly_three_consumers(
    database, tmp_path
):
    bundle = await build_system(
        Settings(
            _env_file=None,
            app_env="test",
            trading_mode="PAPER",
            live_trading_enabled=False,
            database_url=database.url,
            auto_start_runtime=True,
            paper_mode="PAPER_SYNTHETIC",
            llm_secret_store_path=str(tmp_path / "llm-secrets.json"),
            llm_master_key_path=str(tmp_path / "llm-master.key"),
        )
    )
    chief = bundle.engine.strategies[0]
    assert isinstance(chief, ChiefTraderStrategyAdapter)
    assert chief.provider.gateway is bundle.llm_gateway
    assert bundle.daily_review_scheduler.llm_gateway is bundle.llm_gateway
    assert bundle.research_gateway.llm_gateway is bundle.llm_gateway
    assert bundle.llm_gateway.status()["health"] == "NOT_CONFIGURED"
    assert bundle.settings.live_enabled is False
    await bundle.database.close()


async def test_daily_llm_failure_is_retryable_and_does_not_persist_partial_review(database):
    scheduler = DailyReviewScheduler(database.session_factory, llm_gateway=UnavailableGateway())

    try:
        await scheduler.run_once("2026-08-28")
        raise AssertionError("an unavailable daily semantic route must be retryable")
    except DailyLLMRetryableError as exc:
        assert "not_configured" in str(exc)

    assert await MemoryPersistence(database.session_factory).load_daily_reviews() == []


async def test_evolution_llm_failure_returns_no_proposal_and_changes_no_gateway_state():
    gateway = ResearchGateway(llm_gateway=UnavailableGateway())
    gateway.create_experiment({"id": "champion-unchanged", "status": "APPROVED"})
    before = list(gateway.experiments)

    assert await gateway.reason({"source": "immutable"}) is None
    assert await gateway.generate_hypothesis({"source": "immutable"}) is None
    assert await gateway.reason_candidate({"source": "immutable"}) is None
    assert gateway.experiments == before
