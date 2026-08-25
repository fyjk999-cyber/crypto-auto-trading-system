# MEMORY RETRIEVAL EVALUATION

- Implemented: MemoryVectorStore + LocalHashEmbeddingProvider + HybridRetriever.
- Hybrid score = similarity*0.5 + quality*0.2 + recency*0.1 + coin_match*0.1
  + regime_match*0.1.
- Same-symbol is a bonus, not a hard filter.
- Deduplication and quality threshold remain manual/planned; current retrieval
  returns top_k after score sorting.
- No real semantic-embedding model is configured; local deterministic hashing
  embedding is used. No semantic superiority is claimed.
