"""Two-pass bounded source evidence. Existing safety defects are never certified."""

import ast
import hashlib
import json
import sys
from pathlib import Path

from scripts.p41_source_inventory import VERSIONS, git
from scripts.p42r_callgraph import index_sources, reachable, resolved_checkpoint_edges

PREFIX = "shared_market_history."
CP = PREFIX + "storage.checkpoint_store.CheckpointStore."
ATOMIC = PREFIX + "storage.atomic."
LEASE = PREFIX + "storage.writer_lease.WriterLease."
ROOTS = [
    ["__main__._serve", "runtime.SharedHistoryRuntime.serve_forever"],
    ["__main__._backfill"],
    ["backfill.engine.BackfillEngine.run", "backfill.engine.BackfillEngine.run_task"],
    ["maintenance.LandingController._run_stage_cycle"],
    ["maintenance.LandingController._run_incremental_updates"],
    ["maintenance.LandingController._run_deferred"],
    [
        "backfill.background.BackgroundBackfill.start",
        "backfill.background.BackgroundBackfill.state",
    ],
    ["api.server._make_handler.Handler.do_GET", "api.service.SharedHistoryAPI.get_metadata"],
    [
        "observability.stats.StatsService.refresh_snapshot",
        "observability.stats.StatsService._checkpoint_summary",
        "observability.stats.StatsService._coverage_by_timeframe",
    ],
    [
        "__main__._landing_status",
        "__main__._landing_report",
        "maintenance.LandingController.state",
        "maintenance.LandingController._max_1m_freshness_seconds",
    ],
    [
        "storage.checkpoint_store.CheckpointStore." + m
        for m in ("save", "mark_started", "mark_success", "mark_error", "mark_paused")
    ],
    ["storage.atomic.cleanup_stale_temp_files"],
    ["retention.manager.RetentionManager.__init__"],
    [],
    [],
]
KINDS = {
    CP + "load": "CHECKPOINT_READ",
    CP + "list_all": "CHECKPOINT_READ",
    CP + "_dir": "CHECKPOINT_DIRECTORY_CREATE",
    CP + "save": "CHECKPOINT_WRITE",
    CP + "mark_started": "CHECKPOINT_WRITE",
    CP + "mark_success": "CHECKPOINT_WRITE",
    CP + "mark_error": "RECOVERY_RETRY_WRITE",
    CP + "mark_paused": "CHECKPOINT_WRITE",
    ATOMIC + "read_json": "READ_HELPER_DEFAULT_FALLBACK",
    ATOMIC + "atomic_write_json": "ATOMIC_DURABILITY",
    ATOMIC + "atomic_write_text": "ATOMIC_DURABILITY",
    ATOMIC + "atomic_write_bytes": "ATOMIC_DURABILITY",
    ATOMIC + "fsync_dir": "ATOMIC_DURABILITY",
    ATOMIC + "fsync_file": "ATOMIC_DURABILITY",
    ATOMIC + "cleanup_stale_temp_files": "TEMP_DELETE_CAPABILITY",
    LEASE + "acquire": "LEASE",
    LEASE + "release": "LEASE",
}


def fact(index, symbol):
    module, name, node = index["definitions"][symbol]
    info = index["modules"][module]
    return dict(
        symbol=symbol,
        source_sha=index["source_sha"],
        file=info["path"],
        file_sha256=info["digest"],
        function=name,
        line=node.lineno,
        end_line=node.end_lineno,
    )


def handler_binding(index):
    """Reviewed factory assigns api_service=api; concrete type is conditional."""
    module = PREFIX + "api.server"
    function = index["definitions"][module + "._make_handler"][2]
    assignments = [
        n
        for n in ast.walk(function)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "api_service" for t in n.targets)
        and isinstance(n.value, ast.Name)
        and n.value.id == "api"
    ]
    if len(assignments) != 1:
        raise ValueError("handler factory source no longer matches reviewed binding")
    proof = fact(index, module + "._make_handler")
    return {
        (module + "._make_handler.Handler", "self.api_service"): [
            dict(
                constructor=PREFIX + "api.service.SharedHistoryAPI",
                assignment_line=assignments[0].lineno,
                assignment_file=proof["file"],
                assignment=ast.unparse(assignments[0]),
                condition=(
                    "api is runtime-constructed SharedHistoryAPI; "
                    "external factory input not certified"
                ),
                injection_alternative="arbitrary public build_server/api argument",
            )
        ]
    }


def boundary_kind(edge):
    expression = edge["expression"]
    caller = edge["caller_id"]
    if "._timed_ckpt" in caller and expression.startswith("func("):
        return "INTERNAL_CALLBACK_ARGUMENTS_SOURCE_BOUND"
    if ".cached" in caller and expression.startswith("factory("):
        return "INTERNAL_FACTORY_ARGUMENTS_SOURCE_BOUND"
    if caller.endswith("CheckpointStore._observe") and expression.startswith("callback("):
        return "DIAGNOSTIC_CALLBACK_REGISTRATION_BOUNDARY"
    if expression.startswith(("self.checkpoints.", "engine.checkpoints.", "self.engine.")):
        return "INTERNAL_EDGE_UNRESOLVED"
    if any(x in expression for x in ("setattr(", "getattr(", "eval(", "exec(")):
        return "DYNAMIC_DISPATCH_OR_STATE_ATTRIBUTE_REQUIRES_REVIEW"
    return "LIBRARY_VALUE_OR_EXTERNAL_DEPENDENCY_BOUNDARY_NOT_INTERNAL_EDGE"


def one_version(sources, sha, old):
    index = index_sources(sources, sha)
    edges, bindings = resolved_checkpoint_edges(index, handler_binding(index))
    for edge in edges:
        if edge["callee_id"]:
            edge["callee_source_evidence"] = fact(index, edge["callee_id"])
        if edge.get("callback_argument"):
            edge["callback_condition"] = (
                "timed helper invokes func / cached invokes factory / stdlib schedules target; "
                "only supplied binding proven, not execution or authority"
            )
    seeds = set(KINDS)
    # First pass: sinks backwards. Second pass: fixed route roots forwards.
    reverse = reachable(edges, seeds, reverse=True)
    root_ids = [[PREFIX + n for n in names] for names in ROOTS]
    root_ids[13] = ["scripts.capture_service_state.main"]
    forward_by_root = {r: reachable(edges, {r}) for roots in root_ids for r in roots}
    reverse_by_sink = {s: reachable(edges, {s}, reverse=True) for s in seeds}
    forward_sets = [reachable(edges, set(names)) for names in root_ids]
    relevant = reverse | set().union(*forward_sets)
    selected = [
        e
        for e in edges
        if e["caller_id"] in relevant
        and (e["callee_id"] in relevant or e["resolution_method"] == "UNRESOLVED")
    ]
    # Do not inflate business edges with library calls or test-only fixture calls.
    resolved = [e for e in selected if e["resolution_method"] != "UNRESOLVED"]
    unknown = [
        dict(e, boundary_class=boundary_kind(e))
        for e in selected
        if e["resolution_method"] == "UNRESOLVED"
    ]
    critical = [e for e in unknown if e["boundary_class"] == "INTERNAL_EDGE_UNRESOLVED"]
    sinks = [dict(fact(index, s), kind=kind) for s, kind in KINDS.items()]
    sinks.append(
        dict(
            fact(index, "scripts.capture_service_state.sha256"),
            kind="CHECKPOINT_RAW_CONTENT_READ",
            condition="path enumerated under data_root/checkpoints by main",
        )
    )
    routes = []
    for number, (prior, roots, visited) in enumerate(
        zip(old["known_routes"], root_ids, forward_sets, strict=True), 1
    ):
        route_edges = [e for e in resolved if e["caller_id"] in visited]
        route_unknown = [e for e in critical if e["caller_id"] in visited]
        reads = sorted(s for s in seeds & visited if KINDS[s].startswith("CHECKPOINT_READ"))
        writes = sorted(
            s for s in seeds & visited if KINDS[s] in {"CHECKPOINT_WRITE", "RECOVERY_RETRY_WRITE"}
        )
        source = [fact(index, s) for s in sorted(visited & seeds)]
        source.extend(fact(index, r) for r in roots if r in index["definitions"])
        definition_only = number in {12, 13}
        history = number == 15
        classification = (
            "NOT_APPLICABLE"
            if number in {13, 15}
            else "PARTIALLY_RESOLVED_INTERNAL_PATH"
            if route_unknown
            else "PROVEN_DEFECTIVE_INTERNAL_PATH"
            if number <= 11
            else "PROVEN_INTERNAL_PATH"
        )
        if number == 14:
            reads = ["scripts.capture_service_state.sha256"]
            source.append(fact(index, reads[0]))
        routes.append(
            dict(
                ROUTE_ID=f"R{number:02}",
                SOURCE_VERSION=sha,
                ENTRYPOINT=prior["ENTRYPOINT"],
                ENTRY_FUNCTION=roots,
                SOURCE_FILE=[fact(index, r)["file"] for r in roots if r in index["definitions"]],
                CALL_CHAIN_EDGES=[e["edge_id"] for e in route_edges],
                CONCRETE_CHECKPOINT_STORE=(
                    "CheckpointStore default assignments; truthy public injection is external"
                    if number <= 11
                    else "NOT_APPLICABLE"
                ),
                CHECKPOINT_READS=reads,
                CHECKPOINT_WRITES=writes,
                LEASE_ACQUIRE_PATH=[
                    e["edge_id"] for e in route_edges if e["callee_id"] == LEASE + "acquire"
                ],
                LEASE_RELEASE_PATH=[
                    e["edge_id"] for e in route_edges if e["callee_id"] == LEASE + "release"
                ],
                CAS_GUARD="NONE_EXISTING_STORE" if writes else "NOT_APPLICABLE_READ_OR_DEFINITION",
                ATOMIC_COMMIT_PATH=[
                    e["edge_id"] for e in route_edges if (e["callee_id"] or "").startswith(ATOMIC)
                ],
                EXCEPTION_PROPAGATION=(
                    "Postreplace fsync can raise; engine run_task catches "
                    "then mark_error may resave"
                    if writes
                    else "Read defaults merge/skip invalid state; non-CP exceptions not certified"
                ),
                RETRY_PATH="Scheduler cycles/resume; no persistent operation identity"
                if writes
                else "NO_CHECKPOINT_WRITE_RETRY_ON_THIS_CLASSIFIED_PATH",
                MARK_ERROR_PATH=[
                    e["edge_id"] for e in route_edges if e["callee_id"] == CP + "mark_error"
                ],
                CRASH_RECOVERY_PATH=(
                    "No certified COMMIT_OUTCOME_UNKNOWN reconciliation or retry identity"
                ),
                CONSUMER_BEHAVIOR=(
                    "completed/status/freshness consumers remain distinct; no runtime credit"
                ),
                INTERNAL_UNKNOWN_EDGES=[e["edge_id"] for e in route_unknown],
                EXTERNAL_BOUNDARIES=[
                    "Public object/callback injection and later external "
                    "replacement not authenticated",
                    "Installed wrappers/environment/interpreter not inspected",
                ]
                + (["NOT_RECOVERABLE_FROM_AVAILABLE_SOURCE"] if history else []),
                SOURCE_EVIDENCE=source,
                FIXTURE_EVIDENCE=["P42R_TEST_RESULTS.xml; original6strictXFAIL remain unsatisfied"],
                CLASSIFICATION=classification,
                PATH_RESOLUTION_STATUS="NOT_APPLICABLE_HISTORICAL"
                if history
                else "PARTIAL"
                if route_unknown
                else "PROVEN_WITH_RECORDED_CONSTRUCTION_CONDITIONS",
                SAFETY_CONTRACT_STATUS="FAIL_EXISTING_SOURCE"
                if number <= 11
                else "NOT_SAFETY_APPROVAL",
                FORWARD_REVERSE_CROSSCHECK=[
                    dict(
                        entry=r,
                        sink=s,
                        forward=s in forward_by_root[r],
                        reverse=r in reverse_by_sink[s],
                    )
                    for r in roots
                    for s in sorted((seeds & visited) - set(roots))
                    if s in forward_by_root[r]
                ],
                ENTRY_REACHABILITY="PUBLIC_CAPABILITY_ONLY_NO_INTERNAL_CALLER_PROVEN"
                if definition_only
                else "CLASSIFIED_SOURCE_ROUTE",
                HISTORICAL_ORIGIN="NOT_RECOVERABLE_FROM_AVAILABLE_SOURCE"
                if history
                else "CURRENT_PINNED_SOURCE_NOT_HISTORICAL_T0",
            )
        )
    return dict(
        source_sha=sha,
        edges=resolved,
        sinks=sinks,
        boundaries=unknown,
        critical=critical,
        routes=routes,
        bindings=[dict(owner=k[0], receiver=k[1], evidence=v) for k, v in sorted(bindings.items())],
        relevant_definitions=[
            fact(index, s) for s in sorted(relevant & index["definitions"].keys())
        ],
        closure="BLOCKED" if critical else "CANDIDATE_SOURCE_EVIDENCE_ONLY_PENDING_REVIEW",
    )


def main(repo):
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads((root / "docs/P42_TRACKED_SOURCE_COMPLETENESS.json").read_text())
    old = json.loads((root / "docs/P42_CHECKPOINT_CALLGRAPH.json").read_text())
    result = []
    for version, routes in zip(frozen["versions"], old["versions"], strict=True):
        sha = version["source_sha"]
        assert sha in VERSIONS and routes["source_sha"] == sha
        sources = {}
        for f in version["tracked_source_files"]:
            if not f["file_path"].endswith(".py") or f["file_path"].startswith("tests/"):
                continue
            raw = git(repo, "show", f"{sha}:{f['file_path']}")
            if hashlib.sha256(raw).hexdigest() != f["file_sha256"]:
                raise ValueError("fixed source digest mismatch")
            sources[f["file_path"]] = raw
        result.append(one_version(sources, sha, routes))
    for filename, keys in {
        "P42R_INTERNAL_CALL_EDGES.json": ["edges", "relevant_definitions", "bindings"],
        "P42R_CHECKPOINT_SINK_REGISTRY.json": ["sinks"],
        "P42R_DYNAMIC_UNRESOLVED_EDGES.json": ["boundaries", "critical"],
        "P42R_ROUTE_EVIDENCE_MATRIX.json": ["routes"],
    }.items():
        payload = dict(
            schema_version=2,
            versions=[{k: v[k] for k in ["source_sha", "closure", *keys]} for v in result],
            counts_are_not_coverage_ratios=True,
            production_safety="FAIL_EXISTING_SOURCE",
        )
        (root / "docs" / filename).write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    print(
        json.dumps(
            [
                dict(
                    sha=v["source_sha"],
                    edges=len(v["edges"]),
                    critical=len(v["critical"]),
                    routes=len(v["routes"]),
                )
                for v in result
            ]
        )
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m scripts.p42r_reconcile PINNED_GIT_REPO")
    main(sys.argv[1])
