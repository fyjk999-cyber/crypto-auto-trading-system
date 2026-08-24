# Perpetual Architecture

Perpetual futures are a first-class extension of the existing core. Ledger remains the single financial truth.

- `perpetual/domain.py`: contract, margin mode, position side, margin models.
- `perpetual/margin.py`: isolated-margin calculator with tier-provider hook.
- `perpetual/funding.py`: funding payment (long pays when positive rate).
- `perpetual/liquidation.py`: liquidation price and liquidation result.
- `perpetual/ledger.py`: balanced futures journals + replayable futures projection.
- `perpetual/engine.py`: paper perpetual engine (true LONG and SHORT).

ONE_WAY mode first; HEDGE mode deferred (known limitation).
