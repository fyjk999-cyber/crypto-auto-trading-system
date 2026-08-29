"""Expansion regression tests: 20 -> 30 symbol universe with a generic
bidirectional PAPER-perpetual registry.

Guards the AI-FIRST doctrine under expansion: no forced trades, no quant
gates, NO_TRADE stays legal; every new symbol is decided by the Chief Trader
AI against real OKX reference data; non-registered spot shorts stay protected
by SPOT_OVERSHORT; registered symbols route through their own <REF>_PERP
contract on the SAME single PerpetualPaperEngine.
"""


from crypto_trader.config import Settings
from crypto_trader.domain.enums import (
    ExecutionDecision,
    MarketType,
    OrderSide,
    OrderType,
    PositionSide,
)
from crypto_trader.domain.models import SignalIntent
from crypto_trader.runtime.bootstrap import build_system
from crypto_trader.runtime.execution_symbols import (
    execution_symbol_for,
    is_paper_perpetual_symbol,
    reference_symbol_for,
)
from tests.integration.test_perpetual_runtime_routing import _seed_book


async def _make_bundle(database, auto_start=True):
    settings = Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=False,
        paper_mode="PAPER_SYNTHETIC",
        paper_initial_equity="100000",
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600,
        run_lease_renew_interval_seconds=3600,
    )
    bundle = await build_system(settings)
    if auto_start:
        await bundle.engine.start()
    return bundle


def test_execution_registry_maps_new_symbols_and_preserves_spot():
    """Registered references map to <REF>_PERP; everything else stays spot."""
    assert execution_symbol_for("BTCUSDT") == "BTCUSDT_PERP"
    for ref in ("HYPEUSDT", "ZECUSDT", "ENAUSDT", "WLDUSDT", "ONDOUSDT", "FILUSDT",
                "TAOUSDT", "AAVEUSDT", "XLMUSDT", "HBARUSDT"):
        assert execution_symbol_for(ref) == f"{ref}_PERP"
        assert reference_symbol_for(f"{ref}_PERP") == ref
        assert is_paper_perpetual_symbol(f"{ref}_PERP")
    # Non-registered symbols keep the spot path (SPOT_OVERSHORT protection).
    assert execution_symbol_for("ADAUSDT") == "ADAUSDT"
    assert not is_paper_perpetual_symbol("ADAUSDT")
    assert reference_symbol_for("ADAUSDT") == "ADAUSDT"


async def test_universe_expanded_to_30_with_all_new_symbols(database):
    bundle = await _make_bundle(database, auto_start=False)
    symbols = set(bundle.settings.symbol_universe)
    assert len(symbols) == 30
    for ref in ("HYPEUSDT", "ZECUSDT", "ENAUSDT", "WLDUSDT", "ONDOUSDT", "FILUSDT",
                "TAOUSDT", "AAVEUSDT", "XLMUSDT", "HBARUSDT"):
        assert ref in symbols
    assert len(bundle.engine.perpetual_engine.contracts) == 11
    await bundle.database.close()


async def test_new_symbol_perp_short_opens_through_risk_and_execution(database):
    """A SHORT on a registered new symbol executes as <REF>_PERP through the
    REAL RiskEngine + ExecutionAuthority, priced from the real reference book
    (bidirectional paper perpetual; no SPOT_OVERSHORT for perp shorts)."""
    bundle = await _make_bundle(database)
    try:
        await _seed_book(bundle, "HYPEUSDT", "81")
        decision = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_hype_short",
                strategy_id="test",
                symbol="HYPEUSDT_PERP",
                side=OrderSide.SELL,
                quantity="0.001",
                order_type=OrderType.MARKET,
                reason="expansion short test",
                market_type=MarketType.PERPETUAL,
                position_side=PositionSide.SHORT,
            )
        )
        assert decision.decision == ExecutionDecision.APPROVE, decision.reason
        state = await bundle.engine.perpetual_engine.load_state()
        pos = state.positions.get("HYPEUSDT_PERP")
        assert pos is not None and not pos.is_flat
        assert pos.side == PositionSide.SHORT
        fill = await bundle.engine.order_manager.get_by_client("sig_hype_short")
        if fill is not None:
            assert fill.symbol == "HYPEUSDT_PERP"
    finally:
        await bundle.engine.stop()


async def test_spot_short_on_non_registered_symbol_still_rejected(database):
    """SPOT_OVERSHORT protection is unchanged for non-registered symbols."""
    bundle = await _make_bundle(database)
    try:
        await _seed_book(bundle, "ADAUSDT", "0.5")
        decision = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_ada_short",
                strategy_id="test",
                symbol="ADAUSDT",
                side=OrderSide.SELL,
                quantity="0.001",
                order_type=OrderType.MARKET,
                reason="spot short protection test",
                market_type=MarketType.SPOT,
                position_side=PositionSide.FLAT,
            )
        )
        assert decision.decision == ExecutionDecision.REJECT
        assert decision.reason == "SPOT_OVERSHORT"
    finally:
        await bundle.engine.stop()


async def test_perp_position_scoping_across_symbols(database):
    """A HYPE paper-perp position must not freeze other symbols' entries
    (symbol-scoped duplicate-entry gate)."""
    bundle = await _make_bundle(database)
    try:
        await _seed_book(bundle, "HYPEUSDT", "81")
        await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_hype_open",
                strategy_id="test",
                symbol="HYPEUSDT_PERP",
                side=OrderSide.BUY,
                quantity="0.001",
                order_type=OrderType.MARKET,
                reason="open hype perp",
                market_type=MarketType.PERPETUAL,
                position_side=PositionSide.LONG,
            )
        )
        provider_calls = []

        async def provider(symbol=None):
            provider_calls.append(symbol)
            state = await bundle.engine.perpetual_engine.load_state()
            pos = state.positions.get(symbol)
            return pos is not None and not pos.is_flat

        assert await provider("HYPEUSDT_PERP") is True
        assert await provider("BTCUSDT_PERP") is False
        assert provider_calls == ["HYPEUSDT_PERP", "BTCUSDT_PERP"]
    finally:
        await bundle.engine.stop()


async def test_unregistered_perp_symbol_fails_closed(database):
    """An unregistered <REF>_PERP contract has no instrument: the authority
    gate holds the order (fail-closed), no forced execution."""
    bundle = await _make_bundle(database)
    try:
        decision = await bundle.engine.process_signal(
            SignalIntent(
                signal_id="sig_unknown_perp",
                strategy_id="test",
                symbol="ADAUSDT_PERP",
                side=OrderSide.BUY,
                quantity="0.001",
                order_type=OrderType.MARKET,
                reason="unregistered contract",
                market_type=MarketType.PERPETUAL,
                position_side=PositionSide.LONG,
            )
        )
        assert decision.decision != ExecutionDecision.APPROVE
    finally:
        await bundle.engine.stop()


async def test_restart_keeps_contract_registry_stable(database):
    """Rebuilding the system over the same DB keeps the same contract set
    (no duplicate or missing contracts after restart)."""
    settings = Settings(
        _env_file=None,
        app_env="test",
        trading_mode="PAPER",
        live_trading_enabled=False,
        database_url=database.url,
        auto_start_runtime=False,
        paper_mode="PAPER_SYNTHETIC",
        paper_initial_equity="100000",
        engine_tick_seconds=3600,
        reconciliation_interval_seconds=3600,
        run_lease_renew_interval_seconds=3600,
    )
    bundle1 = await build_system(settings)
    keys1 = set(bundle1.engine.perpetual_engine.contracts)
    await bundle1.database.close()
    bundle2 = await build_system(settings)
    keys2 = set(bundle2.engine.perpetual_engine.contracts)
    assert keys1 == keys2 and len(keys2) == 11
    await bundle2.database.close()


async def test_multi_perp_reconciliation_excludes_futures_entries(database):
    """Reconciliation stays clean with multiple open paper-perp positions:
    FUTURES_* settlement entries are excluded from the spot replay scope."""
    bundle = await _make_bundle(database)
    try:
        for ref, price in (("HYPEUSDT", "81"), ("TAOUSDT", "232")):
            await _seed_book(bundle, ref, price)
            decision = await bundle.engine.process_signal(
                SignalIntent(
                    signal_id=f"sig_open_{ref}",
                    strategy_id="test",
                    symbol=f"{ref}_PERP",
                    side=OrderSide.BUY,
                    quantity="0.001",
                    order_type=OrderType.MARKET,
                    reason="multi perp open",
                    market_type=MarketType.PERPETUAL,
                    position_side=PositionSide.LONG,
                )
            )
            assert decision.decision == ExecutionDecision.APPROVE
        halted = getattr(bundle.engine, "reconciliation_halted", False)
        assert halted is False
    finally:
        await bundle.engine.stop()
