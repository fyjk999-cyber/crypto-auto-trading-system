# FACTOR LLM CONTEXT

LLMContext now contains factor_snapshot. Prompt includes Factors line.
LLM tools:
- get_factor_snapshot(symbol)
- get_factor_history(symbol, factor, limit)
- get_market_factor_context(symbol) -> human-readable summary.
Factors are computed by FactorEngine, not by LLM.
