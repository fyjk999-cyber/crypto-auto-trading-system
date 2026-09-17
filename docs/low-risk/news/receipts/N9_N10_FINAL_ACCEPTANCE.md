# N9/N10 News External  Final Acceptance Receipt

Generated: 2026-09-16T16:42:53.417372+00:00

Repository: crypto-auto-trading-system
Branch: codex/low-risk-news-external-evidence-final-closure
Starting SHA: d958e8d66481a5134c8b020e24d5c1f8c47c7626
Code acceptance SHA: 18f0bf5c713894f9fb133a177d510fe4d4991864
Spec SHA: 3caf879b622e2eccd55045900f566cf8bfe02d5e

## Engineering acceptance

- N5 materiality / freshness / novelty / direction: PASS
- N6 canonical Chief context integration: PASS
- N7 reassessment dedup / stale protection: PASS
- N8 outcome review lineage and read-only status API: PASS
- N9 autonomous ingestion worker: PASS
- N10 factual runtime acceptance: PASS

Exact-SHA detached acceptance:

- `pytest tests/news -q` -> 62 passed
- `pytest tests/low_risk -q` -> 291 passed
- `pytest tests -q` -> 1010 passed, 0 failed
- `ruff check src scripts tests` -> All checks passed

## Live factual operation

- Provider: okx_announcements HEALTHY
- Provider: rss_newsbtc HEALTHY
- Provider: rss_cointelegraph DISABLED (network path)
- Aggregate news health: PARTIAL_NEWS_AVAILABLE
- raw news items: 30
- news events: 23
- active news events: 23
- material events: 14
- news evidence: 35
- natural direct-symbol mapping: BTCUSDT, ETHUSDT
- natural deduplicated reassessment requests: 2 (dedup key count 1 each)
- natural completed outcome reviews: 5 via OKX public candles
- outcome observation source: OKX_PUBLIC_CANDLES

No fabricated News or fabricated completion was used.

## Authority boundaries

- NEWS_ORDER_AUTHORITY = NO
- NEWS_NEW_RISK_AUTHORITY = NO
- NEWS_EXIT_AUTHORITY = NO
- CORE_LLM_AUTHORITY_CHANGED = NO
- RISK_AUTHORITY_CHANGED = NO
- EXECUTION_AUTHORITY_CHANGED = NO

## Operational caveats

- Live canonical reassessment requests are queued until the next canonical
  runtime tick; canonical dispatch/dedup was proven on a copy of the natural
  request rows with exactly-once review calls.
- Broad UNIVERSE reviews remain terminal INCONCLUSIVE_DATA_GAP.
- Spread / OI / funding history are explicit unavailable fields.
- FINAL_LOW_RISK_CANDIDATE = NO
