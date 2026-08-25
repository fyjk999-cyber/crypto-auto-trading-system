# FACTOR DECAY

FactorDecayDetector compares old vs new performance (win_rate or sharpe).
>=15% drop => DEGRADING; 10-15% drop => TESTING; otherwise HEALTHY.
Persisted in factor_decay table.
