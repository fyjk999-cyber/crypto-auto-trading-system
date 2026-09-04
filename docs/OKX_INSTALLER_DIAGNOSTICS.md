# macOS installer diagnostic fix

## Finding

The previous installer called `/usr/sbin/dscl`. On the inspected macOS host that
file does not exist; the native executable is `/usr/bin/dscl`. Once the preceding
checks succeed, the first group-creation invocation therefore fails with
`FileNotFoundError` before any group is created. The old catch-all replaced that
exception with `INSTALL_INCOMPLETE`, hiding the cause. No original traceback was
retained, so this finding does not claim to exclude other subsequent failures.

The path is corrected. Tool availability, existing directories/daemon plists and
broken symlinks, client identity, account/group names, two free IDs, source runtime
directories, Git HEAD and deployment assets are checked before the first mutation.
All prior isolation rules remain unchanged; no credentials are enrolled by this fix.

## Read-only preflight

`scripts/install-okx-broker-isolation.sh --preflight` now forwards arguments to
the staged Python entrypoint with bytecode writing disabled. It never reaches
account/group/file creation, Keychain initialization or service installation.

Exit codes: `0` means preflight passed; `1` means a staged failure; `2` means the
ordinary-user checks succeeded but the administrator's sudo-rule audit remains
unverified. A non-root check never claims the privileged audit passed and never
invokes sudo. Normal install requires root as before and reruns all checks.

Actual local preflight completed through `CHECK_ENROLLMENT_TERMINAL` with:

```text
AUDIT_SUDOERS = DEFERRED_ADMIN_REQUIRED
INSTALL_TERMINAL = REQUIRED_FOR_KEYCHAIN_INITIALIZATION
PREFLIGHT_RESULT = ADMIN_AUDIT_REQUIRED
SYSTEM_MUTATIONS = ZERO
CREDENTIALS_ENROLLED = NO
```

## Failure contract

Each phase prints `INSTALL_STAGE` before executing. Failures report stage,
underlying exception class, safe command basename, numeric exit status/errno,
sanitized detail, and `CREDENTIALS_ENROLLED = NO`. Command arguments, exception
free text, stdout, and environment values are never dumped. External stderr is
projected to fixed diagnostic categories; unknown text is withheld rather than
relying on fragile secret-pattern redaction. Interactive hidden Keychain input
retains the trusted helper's terminal and is never captured into diagnostics.

The initial regression reproduced the real nonprivileged entrypoint's swallowed
exception. Tests cover the repaired entrypoint, original missing-tool path,
no mutations on successful/failed preflight, refusal of existing state (including
dangling symlinks), identifier exhaustion, sudo refusal, and secret canaries in
exception/command/stdout/stderr/environment. No host account creation or privileged
installation is performed by tests.

Administrator preflight is the next gate. Actual installation, protected Keychain
initialization and OS isolation remain unverified until their real stages run.

Verification: 23 diagnostic regressions passed; the clean staged canonical
snapshot passed 541 backend tests (one existing Starlette deprecation warning).
Ruff and launcher shell syntax passed. Pre-existing dirty runtime/market/frontend
work was not included in the snapshot or this diagnostic commit.
