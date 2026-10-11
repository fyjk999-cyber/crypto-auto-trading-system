# P4.2-R working evidence, not final acceptance

Base: 2a7ff3319e5c366f571e6ebcac290c2168ed02a4.
Bound directive: reply 74cd5d1b-77b0-49ba-9052-482b301c737e to outbound
5335f876-9ca6-41f1-ae37-547383383156, complete public writing block.

Exact Git source census: producer 107, candidate 110 files. These are separate
counts, not a completion ratio. Frozen P42 evidence is unchanged.

Static candidate edges are a working reverse component closure, not business
route proof. Unresolved receivers, callbacks, injection and external wrappers
are not silently certified. Generated route records explicitly remain pending.

Independent source reviews corroborated:

- CLI main -> _backfill -> engine default CheckpointStore -> worker: no lease.
- Runtime has a separate service lease; store save does not authenticate it.
- Controller/API/stats instantiate additional stores. Reads can mkdir.
- Invalid/missing/unreadable load defaults can feed mark_started/save.
- Replace precedes directory fsync; uncertainty may feed mark_error/save.
- restored_* historical writers remain unrecoverable from available source.

These are source review observations, not final independent package acceptance.
The original six safety XFAILs remain unmet. No actual Shared History source,
production checkpoint/DB, runtime, Quant, Turbo, KB24, strategy or factor changed.

Next in-scope work: reconcile each of 15 routes for each SHA using constructor
and callback evidence, classify sinks, record exact unresolved edge IDs, finish
the specified negative tests and fixed-commit independent package review.
Do not send a final P42R receipt until those deliverables are verified. Do not
enter P4.3, T1, deployment, PAPER or soak.
