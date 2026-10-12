# P4.2-R route-version mapping

Producer25505ff15dd6acd623140d70c0a8eb216c59ea48 and
candidateb1a3f97b213d062ed70375ac7aedbd0d67745a0b are separate records,
not a numerator and denominator. Each route has exact function/edge evidence.
P42_VERSION_DELTA_AUDIT remains the immutable detailed sixteen-file comparison.

| Routes | Source/callgraph difference | Safety/compatibility distinction |
|---|---|---|
| R01 service, R02 CLI, R03 direct engine | Engine ctor68->86; run dispatch1061->1086; candidate adds bounded post-resume freshness tail | Shared Store/lease/atomic unchanged; no safety remediation |
| R04 stage, R05 incremental, R06 deferred | Controller unchanged; engine callee lines shift and 1m tail branch is new | No new owner/CAS/load/retry/durability gate |
| R07 legacy background | Class unchanged; reachable default engine changes as above | External construction remains conditional; not actual service admission |
| R08 API metadata | API/Store unchanged; daily canonical storage behavior outside CP differs | Reads can mkdir; metadata writes not CP writes |
| R09 stats | Stats/Store unchanged; coverage sees storage-domain changes | Snapshot clocks do not imply market freshness or typed load |
| R10 status/report | Controller/report unchanged, downstream storage domain changes | Report writes evidence; lock probe not safe inventory |
| R11 Store public operations | Byte-identical Store and atomic helpers | All original lease/CAS/load/durability failures remain |
| R12 cleanup capability | Byte-identical helper; no internal caller found | No scheduled execution or safety approval inferred |
| R13 retention attribute | Retention source changes for derived daily series | CP attribute construction only; no new CP writer edge |
| R14 capture script | Byte-identical source | Raw CP read/report capability only, never executed |
| R15 historical restored writer | No origin recovered | NOT_RECOVERABLE_FROM_AVAILABLE_SOURCE, no invented equivalence |

Lease, CAS, Load Error, Recovery, Retry and Durability changes for R01–R11:
NONE_IMPLEMENTING_THE_RECOVERY_CONTRACT. Daily canonical/derived namespace and
bounded tail changes stay separate from checkpoint safety. No daily/funding/OI/
market-selection refactor or actual Shared History patch was performed.
