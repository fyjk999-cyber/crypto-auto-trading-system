# Evidence V2 — forward-only candidate

`immutable/` stores new frozen phase artifacts; `manifests/` pins their hashes,
source commit, observation time and predecessor. `mutable-state/` is current task
progress, never proof of an immutable historical state. `attestations/` records
review and external trust status. `verification/` contains offline predicates.

The legacy ledger citation remains FAIL_MISMATCH and original bytes NOT_RECOVERED.
A new version may establish only a current forward baseline, never T0 equivalence.
All hashes and reviews here are same-UID engineering evidence. No independently
controlled archive/key/anchor has been established: INDEPENDENT_CUSTODY=NOT_ESTABLISHED.
Create new versions rather than overwrite old evidence. Git history and file modes
are useful audit aids, not immutability against this UID. A rewritten whole chain
can be locally self-consistent but still cannot acquire formal custody PASS.

Gate Amendment candidate: keep legacy validation status as a required explicit
finding; assess prospective evidence under a separate source-bound custody gate.
Neither the original six-verifier wrapper nor its PASS contract changes here.
Formal amendment/admission remains BLOCKED pending independent review and human
approval of an exact custody/data-read implementation. There is no waiver of G1.
