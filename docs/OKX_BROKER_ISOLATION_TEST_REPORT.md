# OKX Broker OS isolation implementation evidence

Date: 2026-09-05 (Pacific/Auckland).
Base commit: `611c5990c4f3e9f8913aaf2941c638dfa70ce381`.

## Scope

Protected macOS deployment, copied immutable runtime, dedicated identity/private
Keychain, kernel peer authentication, separate credential-free PAPER launcher,
administrator-only enrollment and real OS adversarial verifier. No trading
strategy, risk, execution-authority or live-trading logic changed.

Pre-existing dirty runtime/API-market/frontend files were excluded from staging.
Regression tests use a clean exported index snapshot to avoid folding those
unrelated changes into this task's acceptance.

## Verified nonprivileged results

| Check | Result |
| --- | --- |
| Credential/security suite | 64 passed |
| Full canonical backend regression | 518 passed, one upstream Starlette warning |
| Ruff | PASS |
| Canonical frontend tests | 17 passed |
| Frontend typecheck | PASS |
| Frontend production build | PASS |
| Shell syntax | PASS |
| LaunchDaemon plist syntax | PASS |
| Actual local macOS Unix peer identity | PASS, current-user socket test only |
| `.secrets/okx-paper-credentials.enc` ignore rule | PASS |
| Ordinary-user installer preflight | Correctly refuses: administrator required |
| Actual deployment OS verifier | NOT_INSTALLED; not a PASS |
| Noninteractive sudo listing | Password required |

An initial peer-identity test exceeded macOS's Unix socket path limit in pytest's
default temporary directory. It was corrected to use a short isolated `/tmp`
directory and rerun successfully. No test was disabled to hide the failure.

## Not yet verified

Dedicated user/process UID, installed owner/mode/ACL, private Keychain access
denial, denial of debugging the protected process, privileged service lifecycle,
private Keychain creation/unlock across security sessions, frozen interpreter
relocation/native library audit, real Demo read and protected PAPER launch require
the administrator installation and subsequent actual-machine tests.

No real OKX secrets were read, enrolled, migrated, printed or deleted. No new
Broker service/PAPER process was installed or started by the agent. No claim of
complete OS isolation or successful authenticated Demo operations is made.

## Administrator boundary

The installer performs root's full sudo-rule audit, creates the protected
snapshot, initializes an empty password-protected Keychain via hidden human
input, starts services and runs the actual verifier as the ordinary user.
Real OKX enrollment remains forbidden until this pre-enrollment verifier passes.

Expected next gate: `MACOS_ADMIN_OS_ISOLATION_REQUIRED`.
See [deployment and threat-model notes](OKX_BROKER_ISOLATION.md).
