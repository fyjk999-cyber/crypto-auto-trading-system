"""Derive bounded compatibility rows from the frozen P42R graph, not a rescan."""

METHODS = {"load", "list_all", "save", "mark_started", "mark_success", "mark_error", "mark_paused"}
PREFIX = "shared_market_history.storage.checkpoint_store.CheckpointStore."
PINNED = {"25505ff15dd6acd623140d70c0a8eb216c59ea48", "b1a3f97b213d062ed70375ac7aedbd0d67745a0b"}


def compatibility_matrix(graph):
    versions = graph.get("versions", [])
    if len(versions) != 2 or {v["source_sha"] for v in versions} != PINNED:
        raise ValueError("both pinned versions required")
    rows = []
    for version in versions:
        for edge in version["edges"]:
            if not edge["callee_id"].startswith(PREFIX):
                continue
            method = edge["callee_id"].removeprefix(PREFIX)
            if method not in METHODS:
                continue
            if edge["source_sha"] != version["source_sha"]:
                raise ValueError("cross-version edge")
            file = edge["caller_file"]
            if "observability/stats.py" in file:
                exception = (
                    "leaf propagates; refresher logs and retains old snapshot; "
                    "health can remain OK <=600s"
                )
                adaptation = (
                    "StatsService refresh/error cache invalidation and O(1) degraded health; "
                    "explicit list_all failure"
                )
            elif "maintenance.py" in file:
                exception = (
                    "index propagates; main/deferred loops catch and continue; "
                    "resolution may use 20s cache"
                )
                adaptation = (
                    "LandingController invalid-read and uncertain-commit root quarantine; "
                    "stop both schedulers, invalidate cached resolution"
                )
            elif "api/service.py" in file:
                exception = (
                    "coverage propagates; do_GET catches ValueError400 or generic "
                    "exception500, no normal empty result"
                )
                adaptation = (
                    "preserve valid dict; typed checkpoint failure must not subclass "
                    "request ValueError; existing500 sufficient pending exact type fixture"
                )
            elif "backfill/engine.py" in file:
                exception = (
                    "load defaults hide defects; worker/run_task broad catches "
                    "can mark_error/save again"
                )
                adaptation = (
                    "classify safety exception before business recovery; no mark_error, "
                    "retry or fresh default on safety failure"
                )
            else:
                exception = (
                    "Store no validation, owner or CAS; load defaults; mark_* reads then "
                    "writes; pending_count propagates list failure"
                )
                adaptation = (
                    "strict valid shape plus explicit failures; initialize MISSING only "
                    "under authenticated owner; pending_count must preserve strict errors"
                )
            rows.append(
                {
                    "SOURCE_SHA": version["source_sha"],
                    "FILE": file,
                    "FUNCTION": edge["caller_function"],
                    "CHECKPOINT_METHOD": method,
                    "CURRENT_EXPECTED_RETURN_TYPE": "list[dict]"
                    if method == "list_all"
                    else "dict",
                    "CURRENT_EXPECTED_EXCEPTION_BEHAVIOR": exception,
                    "POST_FIX_EXPECTED_BEHAVIOR": (
                        "VALID retains dict/list; MISSING explicit owner-only initialization; "
                        "other outcomes raise checkpoint-specific failure; "
                        "unknown commit halts root"
                    ),
                    "READ_SIDE_EFFECT": (
                        "legacy load/list_all mkdir; failure defaults/omissions; "
                        "proposed reads no mkdir"
                    ),
                    "ERROR_PROPAGATION": exception,
                    "REQUIRED_ADAPTATION": adaptation,
                    "SAFETY_CLASSIFICATION": "FAIL_EXISTING_SOURCE; PROPOSED_NOT_IMPLEMENTED",
                    "EVIDENCE_REFERENCE": edge["edge_id"],
                    "CALLSITE_LINE": edge["callsite_line"],
                    "FILE_SHA256": edge["caller_file_sha256"],
                    "BRANCH_CONTEXT": edge["branch_and_handler_context"],
                }
            )
    if not rows or any(not any(r["SOURCE_SHA"] == v["source_sha"] for r in rows) for v in versions):
        raise ValueError("vacuous caller census")
    return {
        "schema_version": 1,
        "scope": "existing P42R direct Store edges only; indirect wrappers documented separately",
        "SEVEN_FILE_SCOPE_SUFFICIENT": "NO",
        "ADDITIONAL_CALLER_FILES_REQUIRED": [
            "src/shared_market_history/observability/stats.py",
            "src/shared_market_history/maintenance.py",
        ],
        "API_ADAPTATION": (
            "NO_REQUIRED_CHANGE_WITH_GENERIC_CHECKPOINT_EXCEPTION; "
            "verify exact future exception/HTTP500 before promotion"
        ),
        "P43_C1_C4_SCOPE": "BLOCKED",
        "rows": rows,
    }


def admit(*, reader_scope_complete, historical_schema_proven, restart_unknown_safe):
    # Preparation never grants execution, even when all future inputs are true.
    return {
        "scope": "READY_FOR_SEPARATE_AUTHORIZATION"
        if all(
            type(v) is bool and v
            for v in (reader_scope_complete, historical_schema_proven, restart_unknown_safe)
        )
        else "BLOCKED",
        "implementation": "NOT_STARTED",
        "production": "NOT_GRANTED",
    }
