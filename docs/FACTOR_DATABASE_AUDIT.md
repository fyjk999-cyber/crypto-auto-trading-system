# FACTOR DATABASE AUDIT

- Factor migrations: 0004 through 0013 (10 migrations) plus 0003 AI-memory.
- Schema consistency: all factor tables use String/Numeric/Float/JSON and index
  key columns (symbol, factor_name, research_id, knowledge_id).
- No foreign keys in factor tables (research data is append-only analytics).
- Migration order is deterministic (linear chain).
