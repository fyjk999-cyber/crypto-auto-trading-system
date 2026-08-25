# DATABASE MIGRATION AUDIT

- Migration revisions:
  - 43c806e64582 initial_schema
  - 0002addfence add_fence_generation
  - 0003_ai_memory add AI memory, shadow campaign, capital allocation tables
- Migration 0003 tables: llm_strategy_cards, ai_trade_episodes, ai_trade_reviews,
  ai_market_patterns, ai_coin_profiles, ai_compressed_experience,
  shadow_campaigns, capital_allocations.
- Upgrade/downgrade verified in harness on a temporary SQLite database (upgrade
  path ran 0002addfence -> 0003_ai_memory successfully).
- create_all is used in tests only; migration 0003 is the production schema path.
