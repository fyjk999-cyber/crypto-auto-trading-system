# Backend integration status

The local UI uses existing read-only endpoints: `/health`, `/ready`, `/runtime`, `/account`,
`/positions`, `/orders`, `/killswitch`, and `/ws`.

| Endpoint | UI need | Current result | Expected DTO / impact |
|---|---|---|---|
| `/regime` | Current regime | 404 | Regime, source timestamp, confidence. Overview and signal context show `Not available yet`. |
| `/signals` | Trade evidence / WHY THIS TRADE | 404 | Votes, weights, confidence, leverage path, risk flags, stress result. No client calculation is performed. |
| `/strategies` | Live strategy status | 404 | Effective weight, direction, confidence, reason codes, ML Meta. |
| `/risk` | Portfolio risk state | 404 | Drawdown, multiplier, exposure, leverage, rejects. |
| `/margin` | Position margin and liquidation | 404 | Initial/maintenance margin, liquidation price/distance, funding PnL. |
| `/daily-reviews` | Daily review | 404 | Performance and failure attribution. |
| `/learning` | Learning state | 404 | Candidate/promotion state. |
| `/exchange-health` | Exchange health | 404 | REST/WS health and freshness. |

The UI does not synthesize values for these interfaces and no backend trading-core file was changed.
