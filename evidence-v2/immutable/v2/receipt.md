# P3 forward baseline V2

Exact code source: 6360a7370b31bd76ef9b048ccddbc6566f62574d. New baseline observation: 2026-10-11T18:21:42Z. This is not T0 evidence or production acceptance.

50 tests plus 25 subtests passed; JUnit represents 75 cases, errors/failures/skips zero. Spec and Standards independently reviewed exact source 6360 and reran all 50 tests plus 25 subtests. Their scope is isolated code, not remote delivery, custody, full runtime suite or production admission.

Retained findings: initial adjacent-parent verification lacked recursive ancestor artifact checks (fixed 9b2c284); initial static publication accepted an extra dangling-directory symlink (fixed 6360). A test insertion error produced 1 failed / 49 passed / 25 subtests before correction; no production impact. V1 is preserved byte-for-byte with its original pending-review status.

FORWARD_EVIDENCE_CHAIN = PASS_LOCAL_CONTENT_ONLY
LEGACY_EVIDENCE = FAIL_MISMATCH
ORIGINAL_LEDGER_BYTES = NOT_RECOVERED
INDEPENDENT_CUSTODY = NOT_ESTABLISHED
FORMAL_EVIDENCE_GATE = BLOCKED

A/B/C/E isolated candidates accepted within their limited scope. D is partial: G1-R lacks T1/custody; original G2 budget FAIL retained, universe coverage UNKNOWN; G4/G5.1 not newly accepted. Static KB nine source files/24 models has no runtime activation. Data reader is a contract prototype, fake WAL tests are not a 734MB production certification. Interface is default-disabled pure offline serialization, supplied source labels do not prove authenticated provenance.

No production database content reads, service mutations, deployments, LowRisk boot, Quant Core access, strategy/factor/authority changes, qualification or soak. SOAK_CREDIT=0. Production facts not collected for this baseline remain UNKNOWN.
