# Operational health consumer engineering provenance

Base: 6eda82c8f075ad877460072855bdc137bd01810a (immutable historical candidate).
New branch: codex/lowrisk-operational-health-contract.
The exact new candidate is the commit containing this record, bound by the
external landing ledger and remote verification. This document is not deployment
or runtime acceptance.

The single predicate in shared_history/readiness.py is reused by preflight,
RuntimeHistoryConsumer, and new-envelope adapter validation. It requires schema1,
valid generation/publication, independently current resource/scheduler clocks
within60s, NORMAL resource, running scheduler, and factual PASS outcome with its
original completion timestamp. HIGH/CRITICAL/UNKNOWN, unavailable or malformed
facts fail closed. Legacy heavy aggregate age is not the operational TTL.
Full eligible-universe market freshness remains independent and <=300s; missing,
empty, duplicate, invalid, or incompletely evaluated universes cannot PASS.

The producer-serialized fixture is byte-identical to Shared History fixture:
SHA256347de7ea3f8d46ac7309756f6ea8ab8d0e31faa9178872bbe39377a2eb8cf83e.
Synthetic fixtures are not current host health evidence. Cache is invalidated on
observed operational degradation. No producer writer/admin paths were added.

Isolated tests use candidate source with external APFS HOME/TMP and a filesystem
sandbox denying production state, protected research storage and credentials.
Seven separately audited host tests run through the established external
non-destructive harness; their writes are only test fixtures and unique local
test sockets. News worker fixture directories and Alembic fixture configuration
are explicit temporary/absolute test paths, not application behavior changes.

Existing Chief/Risk/execution/strategy/configuration sources remain unchanged.
Memory and LLM are not activated by this engineering work. Production services
have not been deployed/restarted in this phase. Full test counts, failed isolation
attempts, exact SHAs, remote state and later runtime gates are retained in the
external landing receipt; no local engineering PASS substitutes for them.
