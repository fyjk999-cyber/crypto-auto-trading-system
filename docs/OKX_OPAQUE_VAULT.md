# Opaque OKX PAPER credential bundle

## Status and threat model

Application API isolation is implemented. **OS isolation from this Codex/Harness session is
NOT ENFORCED.** The session has unrestricted filesystem and shell access as the same macOS
user as the broker. That principal can modify the Python program, invoke Keychain APIs,
inspect its own processes, or impersonate a terminal. A private Python method, Unix socket,
0600 file, or TTY check does not prevent those actions by the same principal.

Do not interpret `SECRET_CAN_BE_RETURNED=false` on the documented interface as proof of the
master requirement that an unrestricted same-user agent can never read a credential.
Real-credential acceptance requires the OS separation described below. This change was tested
with randomly generated in-memory fake credentials, not the user's OKX credentials.

## Storage

One logical bundle, `okx-paper-credentials`, holds exactly `OKX_API_KEY`, `OKX_API_SECRET`, and
`OKX_API_PASSPHRASE`. Its file is `.secrets/okx-paper-credentials.enc`.

The envelope is versioned magic + random 96-bit nonce + AES-256-GCM ciphertext/tag. The bundle
name and format version are authenticated as associated data. Each save uses a fresh nonce.
Only encrypted bytes are written to a temporary file before atomic replacement. The directory
requires 0700 and the file 0600; symlinks and unsafe ownership/modes are rejected. A corrupt,
truncated, wrong-key, or modified envelope fails closed. The AES key is 32 random bytes stored
only in macOS Keychain, service `crypto-auto-trading-system`, account
`okx-paper-credentials-aes256-key`. A missing encryption key for an existing envelope is not
silently replaced.

Python strings and third-party crypto/network libraries may create memory copies that cannot
be reliably zeroed. References are cleared promptly; mutable plaintext buffers are overwritten;
core dumps are disabled for the broker launch. This is not a claim of protection from root,
same-user debugging, swap, or a compromised broker interpreter.

`.secrets/` was already gitignored and remains excluded. No credential material or encrypted
bundle is committed. Old OKX per-field Keychain items, if present, have NOT been read, migrated,
or deleted. The former Swift raw loader has been removed; `okx-keychain.sh` now forwards only
to the new human CLI. Existing credential backups/old checkouts need operator inventory and
revocation/cleanup during protected deployment; this implementation cannot erase unknown copies.

## Broker operations

The service listens on `.secrets/okx-broker.sock`, not TCP. File locking prevents a second
broker owning that endpoint. Agents and the control plane use `okx_vault.client.BrokerClient`:

```python
client = BrokerClient()
await client.verify()
await client.configured()
await client.credential_status()
await client.validate_okx_demo()
await client.signed_request("GET", "/api/v5/account/config")
await client.run_paper()
```

No read, load, get_credentials, export, dump, save, delete, or signing-material RPC exists.
Unknown operations and unexpected arguments are denied. Requests are bounded to 8 KiB and
55 seconds. Signed requests are serialized and paced. The only allowed operations are GET
with no body, query string, custom host, custom header, redirect, or caller-controlled transport:

- `/api/v5/account/config`
- `/api/v5/account/balance`
- `/api/v5/account/positions`
- `/api/v5/trade/orders-pending`

The fixed upstream is HTTPS `openapi.okx.com`; every authenticated request sends
`x-simulated-trading: 1`. No exchange order placement, cancellation, transfer, withdrawal,
credential administration, or LIVE request is available. An agent cannot use this broker to
bypass canonical Risk/Execution gates. Local PAPER execution continues in the simulator.

The broker computes OKX HMAC-SHA256 signatures internally. It projects upstream replies into
an explicit field schema and rejects credential/signature echoes, including common encodings.
It never returns request headers, upstream free-text errors, raw response bodies, exceptions,
or arbitrary response fields. Transport errors use fixed safe error codes. Network response
size is bounded to 1 MB, timeout is 10 seconds, redirects and ambient proxy configuration are
disabled. Time/signature failures fail closed; no synthetic result is substituted.

## PAPER launch and application integration

`run_paper` accepts no caller-supplied command, environment or port. It launches the existing
`crypto_trader.runtime.local_runner` on 127.0.0.1:8000 and forces:

```text
OKX_DEMO=true
TRADING_MODE=PAPER
PAPER_MODE=PAPER_REAL_MARKET
LIVE_TRADING_ENABLED=false
```

The child receives only the broker socket path for OKX authentication. **No OKX API credentials
are injected into the child.** This implements the preferred broker-side-signing option rather
than the optional environment fallback. Test requirement 9 is therefore covered by proving
the child receives the usable broker capability while neither child nor parent-facing response
receives raw secrets. Only an explicit environment allowlist is forwarded. The official local
runner ignores old OKX credential environment/file values. The launcher refuses an occupied
8000 port and returns the existing child for duplicate start requests. The canonical execution
lease remains the final single-writer authority. A returned PID is a spawn receipt, not health
or successful trading-loop acceptance.

The HTTP `/exchange/okx/status` and `/exchange/okx/validate` routes use the broker client.
POST/DELETE `/exchange/okx/credentials` return 403 without parsing a credential model (avoiding
validation-error echoes). The old `EnvCredentialStore` rejects read/write/delete. The web form
no longer accepts credentials or displays even a key suffix.

The currently running 8000 process from another checkout has NOT been restarted by this change.
It does not gain the new behavior merely because source files were edited. Deploy the verified
checkout under the protected process identity before claiming production acceptance.

DeepSeek decision authority, quant evidence, Risk APPROVE/SCALE_DOWN/REJECT, and Execution
authority were not changed. This work does not validate autonomous trading acceptance.

## Human-only enrollment commands

After the protected deployment is in place, run in its canonical project directory:

```bash
./scripts/okx-vault.sh save
./scripts/okx-vault.sh verify
./scripts/okx-vault.sh run
./scripts/okx-vault.sh delete
```

Save collects all three fields with hidden terminal input. Never supply values as arguments,
chat messages, `.env` entries, or redirected files. Delete requires a local TTY and an explicit
DELETE confirmation, and is not offered over the agent API. A TTY check alone does not prove a
human is present when an agent can allocate PTYs. Deletion cannot recall in-flight requests or
erase previously made copies. The CLI can install a per-user LaunchAgent named
`com.crypto-trader.okx-credential-broker`; this local development arrangement is not OS isolation.

If `.secrets` already exists with unsafe permissions, the command fails instead of silently
altering permissions of unrelated files. The operator must establish the intended private
directory ownership and 0700 mode. Keychain permission prompts require human interaction.

## Mandatory protected deployment before master-security acceptance

An administrator must establish a security boundary outside the agent's authority:

1. Run the broker and human enrollment under a dedicated macOS user or a suitably signed,
   sandboxed broker identity. Protect its code, interpreter, libraries, Keychain and encrypted
   bundle from agent reads/writes/debugging. A mutable shared project/interpreter is unsuitable.
2. Give the agent only an authenticated IPC gateway to the allowlisted broker operations.
   For a dedicated user, keep the vault directory private and expose a separate IPC socket
   through narrowly scoped ACLs or a protected gateway. Never grant access to the vault path
   merely to allow traversal to a colocated socket.
3. Remove agent access to the broker user's shell, Keychain tools, filesystem, debugger,
   enrollment/deletion command and privilege escalation. Protect human approval mechanisms.
4. Inventory old per-field Keychain items, environment entries, old running processes and
   backups, then revoke or retire obsolete credentials under human control.
5. Repeat adversarial tests from the actual restricted agent identity: raw decrypt/import,
   keychain lookup, process inspection, program replacement, delete and export must be denied
   by the OS while approved IPC operations succeed. Enroll real credentials only through the
   protected human terminal, then perform a real Demo read-only validation.

This session cannot truthfully attest those OS permissions: it currently has unrestricted
same-user shell and filesystem access. Administrator-controlled isolation and human enrollment
are outstanding user actions. No real bundle or AES key was created during automated tests.

## Verification evidence

- **Release/index-only snapshot:** 502 backend tests passed, one upstream warning (48.98 s);
  17 frontend tests passed, frontend typecheck/build passed, repository Ruff passed.
  This excludes unrelated local market collector/runtime edits. Final added DEBUG-log and
  live-broker-isolation assertions also passed the 48-test credential suite.
- The first index-only check found three stale pre-existing assertions (Alpha entry authority
  and Binance fallbacks). They were corrected to the already accepted Live LLM / OKX behavior;
  no trading implementation was changed to satisfy them. Five baseline Ruff warnings were
  resolved using the existing formatting-only edits to `0007_factor_v3_tables.py` and
  `performance_smoke.py`; AST comparison confirmed identical behavior.
- Initial full working-tree backend regression: 510 passed, one upstream Starlette/httpx warning.
- Final dedicated credential suite after additional permission/launch tests: 48 passed.
- Frontend working-tree suite: 19 passed; typecheck and production build passed.
- Ruff and shell syntax checks passed.
- Real local Unix-socket service started. `verify` returned `VAULT_UNAVAILABLE` because the
  new bundle is not enrolled; this is expected fail-closed behavior, not real OKX authentication.
- Unit/integration tests use an injected ephemeral random key provider and mocked HTTP transport.
  They cover authenticated encryption, fresh nonces, restarts, corruption, file modes, symlinks,
  atomic replacement failures, exact signatures, DEMO headers, sanitized successful and hostile
  replies, exception/log non-disclosure, RPC denials, empty account config, read-only validation,
  child environment isolation and duplicate-start protection. A generated-material repository
  scan is included; it is not proof that unknown historical secrets never existed.

Pre-existing unrelated work remains unstaged: market collector files and report, market-page
navigation/style/chart changes, `.gitignore` market-data entry, runtime log/PID, runtime bootstrap,
AI adapter, market state, simulated real-market adapter, OKX feed and LLM strategy draft files.
Only the two OKX expectation hunks in the pre-existing market semantics test are included;
its feed-related edits remain local. The two pre-existing formatting fixes above are included
intentionally to make the release lint gate reproducible. The earlier raw OKX script/store
changes are superseded by this authorized vault replacement. Existing credential items were
not deleted. All security implementation, CLI, HTTP integration and UI credential-panel changes
are in this commit; no actual credential, encrypted document, data log, PID or `.secrets` file is staged.

Sources: [cryptography AESGCM](https://cryptography.io/en/stable/hazmat/primitives/aead/),
[Apple Keychain isolation](https://developer.apple.com/documentation/security/sharing-access-to-keychain-items-among-a-collection-of-apps),
[Apple code signing and access policies](https://developer.apple.com/library/archive/technotes/tn2206/).
