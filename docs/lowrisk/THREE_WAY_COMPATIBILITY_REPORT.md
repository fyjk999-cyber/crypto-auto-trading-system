# LowRisk three-way compatibility review

## Factual baseline (2026-10-04 Asia/Shanghai)

Runtime `/version` reports 6ced1da3008edf49eac086596ff4f208ee7b0821.
launchctl com.lowrisk.paper PID790 and lsof cwd bind it to the immutable deployment
`/Users/huhongjie/Library/Application Support/LowRisk/deployments/final-candidate-2-6ced1da`.
That deployment Git HEAD matches. The interpreter is from lowrisk-final-landing's
venv; this alone does NOT establish loaded source identity. Wrapper PYTHONPATH points
to deployment src. Runtime `/runtime`: PAPER, lease held, provider_calls_paused true.
`/cloud-status`: live_trading_enabled false. `/llm/health`: configured DeepSeek,
deepseek-flash, PROVIDER_PAUSED, effective provider/model null. No credentials read.
Current source landing HEAD374ee96022d0360d49dc4a8dbaa1619e2a1fbe54 detached with
untracked data/acceptance; left intact. Remediation HEADa5cae82440f54b73b7143ec4ba4a689bbcf49382
clean on codex/final-master-remediation. Neither historic directory HEAD overrides
the factual deployed baseline.

Shared History source B is frozen45a282621728a4aec39683a1ada035ce199ee1f6;
its implementation is76564e7440e67dfda2e87050d94575056873d8bf. Endpoint defaults
http://127.0.0.1:8770, disabled in candidate Settings. Deployed6ced has no such
integration package: production integration NOT_ACTIVE. Current GET/v1/health
reports SHA76d0830, writer1 and OK but lag23536.103s, updater WAITING, and no
explicit resource_state. This snapshot is NOT qualification or freshness PASS.
No universe qualification was run; reported universe_size485 is merely a dated
API observation, never an acceptance constant.

## Relevant delta classification

| Delta | Classification | Disposition |
| --- | --- | --- |
| 6ced1da durability path guard and canonical tool budget/repair | REQUIRED | Preserve deployed fix, merge into newer remediation; no runtime mutation |
| 21ca583 as-of Chief/tool context | REQUIRED | Preserve no-lookahead evidence correction |
| e630892 factor persistence/tools | REQUIRED | Evidence plumbing, no factor thresholds/direction votes; preserve current source |
| a5cae82 factor/memory as-of | REQUIRED | Preserve temporal purity |
| 76564e7 config/client/adapter/tests/probe | REQUIRED | Review/merge GET-only seam, default disabled |
| 45a2826/1ec70f1/4bf860e receipts | DOC_ONLY | Historical receipts, not current qualification; not copied as PASS |
| historical artifacts carried by76564e7 | DOC_ONLY | Labeled historical and never gate inputs |
| new fixtures and prohibition scanner | TEST_ONLY | Synthetic temp data/loopback only |
| 374 baseline without6ced durability/tool corrections | SUPERSEDED | Not activation baseline alone |
| global candidate wholesale deployment during migration | UNSAFE | Not performed |
| feature cache lacking requested version | CONFLICTING | Fixed version key plus response provenance verification |
| automatic HTTP redirects/proxies escaping localhost | CONFLICTING | Refuse redirects, disable proxy inheritance |
| cached healthy history after degraded health | CONFLICTING | Clear/block observed degraded cache; runtime port checks fresh health before reads |
| latest ML/code changes from unrelated ML workspaces | UNSAFE | No blind merge/model promotion; existing deployed ML implementation retained |
| full Symbol Memory Phase B/index/backfill | UNSAFE | Interface-only read port; no backend activated |

One branch/worktree: codex/lowrisk-post-migration-ready,
/Users/huhongjie/lowrisk-post-migration-ready, starting a5cae82.
Reviewed merge bases: A/C share374ee96; B descends from factual deployed6ced.
Risk/execution/strategy source trees and economic settings must byte-match6ced;
only disabled evidence configuration and engineering temporal/history code may differ.

## Review axes

Code-review skill independent Standards found redirect escape plus optional
timestamp-code duplication/mutable record concerns. Spec found feature-cache purity,
degraded cache, missing runtime port, missing runbook. Required defects are corrected
and regression-tested. Evidence remains non-authoritative and default off.

AppleDouble protection is by API-only boundary here: LowRisk has no Parquet reader
or DuckDB connection. No local filter/writer is imported from Shared History.
Upstream centralized factual filtering must independently be verified at activation;
this candidate does not claim to implement or redeploy Shared History filtering.
