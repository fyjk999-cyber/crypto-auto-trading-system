# FORWARD SHADOW PROTOCOL

- Real OKX market data only; no synthetic fallback.
- Decision timestamp strictly before label maturity; no lookahead.
- Structured decision records with decision_ts, label_maturity_ts, outcome_window.
- Replay tests are labeled REPLAY and never count as forward evidence.
