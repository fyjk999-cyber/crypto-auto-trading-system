from crypto_trader.exchange.okx import OKXAdapter


class FundingHistoryAdapter(OKXAdapter):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def _public_request(self, method, path, params=None):
        self.calls.append((method, path, params))
        return {
            "data": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "fundingTime": "1789084800000",
                    "realizedRate": "0.0001",
                }
            ]
        }


async def test_funding_rate_history_uses_factual_endpoint():
    adapter = FundingHistoryAdapter()
    rows = await adapter.get_funding_rate_history("BTC-USDT-SWAP", limit=500)
    assert rows[0]["realizedRate"] == "0.0001"
    method, path, params = adapter.calls[0]
    assert method == "GET"
    assert path == "/api/v5/public/funding-rate-history"
    assert params == {"instId": "BTC-USDT-SWAP", "limit": 100}
