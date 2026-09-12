import httpx

from crypto_trader.ai_brain.decision.decision_engine import AITradingBrain
from crypto_trader.runtime.ai_position_bridge import AIPositionRuntimeBridge
from crypto_trader.shadow_campaign.forward_metrics import ForwardMetrics


async def test_real_okx_forward_data_smoke_and_metrics():
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": "BTC-USDT-SWAP", "bar": "15m", "limit": "30"},
        )
    assert response.status_code == 200
    rows = response.json()["data"]
    assert len(rows) >= 20
    brain = AITradingBrain()
    entry = brain.analyze(
        symbol="BTC-USDT-SWAP",
        market_state="TRENDING",
        direction="LONG",
        thesis="real okx candles",
        supporting=["real candles"],
        confidence=0.6,
    )
    assert entry.action in ("OPEN_LONG", "NO_TRADE")
    bridge = AIPositionRuntimeBridge()
    evaluation = bridge.evaluate(
        symbol="BTC-USDT-SWAP",
        active_position={
            "quantity": 0.1,
            "side": "LONG",
            "thesis_status": "THESIS_INTACT",
            "thesis": "trend",
        },
    )
    assert evaluation.action in ("HOLD", "COOLDOWN", "EXIT")
    metrics = ForwardMetrics()
    metrics.record(confidence=0.6, result="WIN", pnl="1")
    metrics.record(confidence=0.6, result="LOSS", pnl="-0.5")
    assert metrics.total_trades == 2
    assert metrics.to_dict()["calibration"] in (
        "INSUFFICIENT_EVIDENCE",
        "PASS",
        "OVERCONFIDENCE_RISK",
    )
