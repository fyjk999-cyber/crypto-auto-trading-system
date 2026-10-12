# Source membership and limits

P42R_SOURCE_SCOPE_MANIFEST enumerates all selected fixed extension source files,
including test-only files. Graph construction excludes test files and never
imports source. It verifies bytes against the immutable P42 source index.

Collections are actual member lists, not numeric coverage ratios:

- Relevant definitions: exact function symbols, spans and source hashes in
  INTERNAL_CALL_EDGES.relevant_definitions. Reverse traversal starts from
  classified Store/atomic/lease capabilities; forward traversal from route roots.
- Relevant callsites: resolved edge members plus boundary callsite members,
  with unique SHA/file/line/column IDs.
- Resolved internal edges: direct static, imports (including function-local
  imports), constructor-bound receivers and explicitly supplied callbacks.
  Applicability records the default-construction condition, not authority.
- Unresolved internal edges: critical members of DYNAMIC_UNRESOLVED_EDGES;
  library values are separate, not falsely counted as unresolved CP writers.
- External boundaries: public injections and overrides, third-party scheduling,
  installed argv/environment, and historical unavailable source. The generic
  boundary list is conservative; non-CP library edges are not security PASS.
- Read/write/atomic/lease/recovery capability sets: classified definition
  members in CHECKPOINT_SINK_REGISTRY. Shared atomic helpers are context-dependent:
  their existence alone does not establish a CP destination.

Callbacks: known timing/factory helpers invoke supplied functions; thread/executor
edges only prove registration under conditions, not that a task executed.
HTTP handler factory source assigns api_service=api; conditional receiver type
is the runtime-assembled SharedHistoryAPI, not arbitrary external factory inputs.
No annotations are treated as runtime type enforcement.

The graph's forward/reverse check is a consistency check on the same edge set,
not independent evidence of missing-edge absence. Human source reviews and fixed
commit Spec/Standards reviews are required. Mutable monkey-patching/inheritance,
reflection and factory inputs outside these recorded conditions remain unknown.
ALL_RUNTIME_ENTRYPOINTS_PROVEN is never claimed.

R12 cleanup has no discovered internal caller; R13 retention is construction-only;
R15 historical origin is NOT_RECOVERABLE_FROM_AVAILABLE_SOURCE. These are not
silently converted into active runtime paths or historical source equivalence.
