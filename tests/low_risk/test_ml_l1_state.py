from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_market_state_l1_defaults_are_explicit():
    from crypto_trader.market_data.state import MarketState

    state = MarketState(symbol="BTCUSDT")
    assert state.bid_size == 0 and state.ask_size == 0 and state.imbalance_l1 == 0


def test_scanner_l1_sizes_flow_into_snapshot_imbalance():
    source = (ROOT / "src/crypto_trader/market_data/opportunity/service.py").read_text()
    assert "bid_qty=float(state.bid_size)" in source
    from crypto_trader.market_data.opportunity.factors import SymbolFacts
    from crypto_trader.market_data.opportunity.snapshots import decision_time_features

    features = decision_time_features(SymbolFacts(symbol="X", bid_qty=3.0, ask_qty=1.0))
    assert features["l1_imbalance"] == 0.5
