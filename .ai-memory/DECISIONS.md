# DECISIONS

- 2026-08-27T00:14:33.078993+00:00: FactorSnapshot is deeply immutable via frozen dataclasses +
  MappingProxyType + tuples. Live factor access is canonical through
  FactorToolGateway. Daily learning uses historical snapshots only.
