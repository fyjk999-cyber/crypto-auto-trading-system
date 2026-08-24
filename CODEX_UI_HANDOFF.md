# CODEX_UI_HANDOFF

Codex can build the Web UI without reading trading-core internals.

## Architecture
Trading API (FastAPI) serves JSON. WebSocket pushes real-time events.
Backend remains the only source of truth (ledger + projections).

## API base URL
`http://<host>:8000`

## OpenAPI
FastAPI exposes `/docs` and `/openapi.json`.

## WebSocket path
`/ws` (event envelope: `event_type`, `event_version`, `timestamp`, `payload`).
Events include market, regime, signal, position, margin, order, fill, PnL,
risk, review, stress, alert, runtime, exchange-health.

## Auth
Optional API key header `X-API-Key` for control endpoints. All POST control
endpoints must be authenticated, authorized, and audited.

## Data models
- LONG position side: `LONG`; SHORT position side: `SHORT`; FLAT: `FLAT`.
- Margin fields: `initial_margin`, `maintenance_margin`, `available_margin`,
  `margin_ratio`, `liquidation_price`.
- Leverage fields: `recommended_leverage`, `risk_capped_leverage`,
  `review_approved_leverage`, `effective_leverage`.
- Review workflow: L1-L4; L4 `WAITING_APPROVAL` then approve/reject.
- Kill switch: `POST /kill-switch/on` and `/off`.
- Daily review: `GET /daily-reviews`.
- Learning state: `GET /learning`.
- Exchange health: `GET /exchange-health`.

## Error handling
Errors use a normalized `{error: {code, message, retryable}}` envelope.
