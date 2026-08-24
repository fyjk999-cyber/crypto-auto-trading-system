# Liquidation

Liquidation is evaluated on mark price, not last trade price.
Liquidation price formulas:
- LONG: entry - (initial_margin - maintenance_margin) / position_qty
- SHORT: entry + (initial_margin - maintenance_margin) / position_qty

Liquidation closes the position in the ledger and is auditable/replayable.
