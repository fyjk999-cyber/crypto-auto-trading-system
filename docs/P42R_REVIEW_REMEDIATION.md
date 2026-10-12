# Independent review findings retained

First reviewed candidate7f6fd8d74250b99defbce62f971e66d86d49e18f:
Spec REQUEST_CHANGES (2 findings), Standards REQUEST_CHANGES (3 findings).
No source closure or production safety acceptance was granted.

| Axis | Finding | Isolated remediation / negative |
|---|---|---|
| Spec | Missing branch conditions | IF/ELSE/EXCEPT callsite contexts; test_branch_and_exception_context_is_recorded |
| Spec | Direct Store given engine retry claims | R11 now says direct exceptions escape, retry not proven |
| Standards | Module rebinding retained old import edge | Conservative module assignment/deletion rejection; test_module_rebinding_and_deletion_do_not_resolve_old_import |
| Standards | .submit suffix invented callback invocation | Actual source parameter invocation required, or exact imported stdlib Thread/ThreadPoolExecutor registration; test_noop_submit_cannot_manufacture_callback_reachability |
| Standards | Empty/missing version inventories accepted | Both exact ordered SHAs and exact R01–R15 IDs; test_version_inventory_cannot_pass_vacuously |

Reviewed temporary pure AST fixtures reproduce the first-candidate defects.
These findings apply to the engineering evidence tools, not actual Shared
History implementation patches. Original checkpoint security XFAILs remain.
Successor fixed-commit review is required; this document does not self-approve.

Successor1296d0995a3c0a6543fb23f8a61edc20a1ae6c5c:
Spec PASS_SOURCE_EVIDENCE_ONLY; Standards REQUEST_CHANGES for two remaining
callback identity gaps. A called parameter could have been rebound, and a
ThreadPoolExecutor variable could have been replaced by a Noop before submit.
Conservative parameter Store/Del/redefinition rejection and exact with-body,
unreassigned receiver checks address these. New negative fixtures preserve
both reproductions. Another exact successor review is required.
