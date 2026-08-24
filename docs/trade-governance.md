# Trade Governance

- Risk levels L1-L4. L1 automatic; L2 RiskReviewer; L3 adds AdversarialReviewer;
  L4 adds human approval. L4 timeout rejects (never auto-approve).
- Reviews are deterministic and structured (`ReviewDecision`, risk_score, flags).
- Leverage chain: recommended -> risk_capped -> review_approved -> effective.
