# FACTOR ARCHITECTURE

Market Data -> Factor Engine (calculators) -> FactorResult list -> SnapshotBuilder
-> FactorSnapshot -> FactorService persistence -> LLM tools (read-only).

Calculators: trend, momentum, volatility, volume, orderflow, funding, open_interest.
Factor Engine never places orders or makes trading decisions.
