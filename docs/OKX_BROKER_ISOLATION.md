# macOS OKX Broker isolation

## Boundary and current acceptance

This deployment replaces the obsolete same-user LaunchAgent with a dedicated
`crypto-okx-broker` LaunchDaemon. It does not change decision, risk or execution
authority. DeepSeek remains directional authority; quant is evidence-only.

Do not claim OS isolation from Python unit tests. The normal-user verifier must
run on the installed machine. Until administrator installation succeeds,
`OS_LEVEL_UNREADABILITY = NOT_INSTALLED`, and authenticated Demo/PAPER operations
are **NOT_VERIFIED**. No real OKX credentials are enrolled during implementation
or installation.

## Layout

| Location | Owner / protection | Purpose |
| --- | --- | --- |
| `/Users/crypto-okx-broker` | broker, 0700 | no login shell; private home |
| `~broker/.crypto-okx/vault` | broker, 0700; envelope 0600 | encrypted bundle |
| `~broker/Library/Keychains/okx-broker.keychain-db` | broker, 0600 inside 0700 parents | AES key; independent password-protected Keychain |
| `/Library/Application Support/CryptoOKXBroker/runtime` | root, non-writable by agent or broker | copied standalone Python, dependencies and committed application |
| `.../ipc/broker/broker.sock` | broker, group-restricted 0660 | kernel peer-UID authenticated operations |
| `.../ipc/paper/paper.sock` | main user, group-restricted 0660 | credential-free fixed PAPER launcher; accepts only broker UID |
| `.../paper-state` | main user, 0700 | separate PAPER database/state, never vault/keychain |
| `/Library/LaunchDaemons/com.crypto-trader.okx-*.plist` | root, 0644 | dedicated Broker and credential-free main-UID launcher |

Source is readable (root-owned 0755/0644), but is NOT writable by agents. This is
the explicit source-readability exception in the task; secret/home/Keychain access
remains private. Copying code is not authorization to decrypt anything.

The two socket directories are separate: the main user cannot replace the Broker
socket or its parent. The main user can tamper with its own PAPER launcher/state,
but that launcher has no OKX credential access and cannot change Broker signing
policy. Never run the full trading web application under the credential owner.

## Administrator installation (one command)

From the canonical repository, in a human terminal:

```sh
sudo ./scripts/install-okx-broker-isolation.sh
```

The installer prompts, with hidden input, for a **new private Keychain password**
(12+ characters) and confirmation. This is NOT an OKX API key. Remember it outside
the repository/chat. No password is saved in environment, arguments or files.
The empty private Keychain contains no AES key/OKX secret before enrollment.

Installation refuses existing accounts/homes/deployment paths and NOPASSWD sudo
rules instead of adopting, overwriting, deleting or weakening them. Partial
installation is preserved for investigation; do not blindly remove it or rerun.
The old same-user LaunchAgent is stopped/renamed, retaining all old credential
data. No credential migration occurs.

Legacy copies previously saved in the main user's Keychain are **not** protected
retroactively by this deployment. This verifier proves the new private bundle's
boundary, not the absence of every historical copy. Before asserting global
credential unreadability, the human should enroll newly issued Demo credentials
and revoke old ones, or independently remove all legacy copies. The installer
does not read, migrate or delete them without authorization.

The interpreter and all site-packages are copied, with symlinks dereferenced,
editable hooks removed and root ownership applied. Application source comes from
committed HEAD, not dirty runtime work. Native loaded library locations are
checked. Installation executes reviewed code/dependencies as administrator;
inspect that code before approving sudo. Future updates require administrator
review of a new snapshot; editing the worktree does not update the Broker.

## Actual pre-enrollment verification

The installer automatically runs the protected verifier as the main user with
explicit groups. It checks actual owner/mode/ACL and file-open denial, kernel peer
identity, `task_for_pid` denial, sudo/su/launchctl restrictions, private Keychain
access, shared native-library paths and denied save/delete/export RPCs.
An ENOENT, timeout or unavailable test tool is NOT accepted as denial.

The probe opens files without reading, writing or truncating them. `security`
output is discarded even if an unexpected access succeeds. Process output is
captured and never displayed. No debugger reads memory. Core dumps are disabled.
The vault directory contains a clearly labelled **non-secret permission probe**,
not a fake encrypted credential bundle. Admin initialization establishes the
empty private Keychain before permission probing.

Run again as the ordinary user:

```sh
./scripts/verify-okx-broker-isolation.sh
```

Pre-enrollment PASS covers OS isolation only, not a successful authenticated OKX
request. It explicitly reports Demo authentication and PAPER launch NOT_VERIFIED.
Supplementary group membership may require restarting the calling application.

## Enrollment after OS verification

Only the protected administrator command can enroll/update/delete/unlock:

```sh
sudo "/Library/Application Support/CryptoOKXBroker/runtime/bin/python3" -I -m crypto_trader.okx_vault.enrollment save
```

Before accepting credentials it reruns OS verification under the main UID, then
drops to the broker UID, clears environment, changes to the private home and uses
hidden terminal input. No arguments/stdin redirect/environment credential input.
It asks for the private Keychain password, then the three OKX Demo values. There
is no export/read command. Replace `save` with `delete` for human-confirmed removal
or `unlock` after a reboot/Keychain lock. Root authentication is required for all.

The Keychain password is not persisted, so unattended reboot unlock is
deliberately unavailable. A locked Keychain fails closed; it never produces a
synthetic success, trade or fake credential. Unlocking may require restarting a
failed daemon after investigation; never weaken Keychain encryption to bypass it.

Normal-agent operations:

```sh
./scripts/okx-vault.sh verify
./scripts/okx-vault.sh run
./scripts/verify-okx-broker-isolation.sh --operations
```

`--operations` performs factual Demo reads and requests a fixed PAPER runtime
launch, so use it only after enrollment. It does not place orders. The launcher
refuses an occupied backend port, preserves an existing child and provides no
arbitrary command/URL/header/environment endpoint. Protected Broker never passes
OKX plaintext through a subprocess environment; runtime uses Broker signing.
The separate PAPER deployment does not import the main user's DeepSeek Keychain
secret or existing mutable database. Missing LLM configuration fails closed and
is not a claim of complete autonomous trading acceptance.

## Limits and recovery

Root/admin-approved code, OS compromise and deliberate administrator access are
outside this boundary. Any passwordless sudo rule is conservatively blocked.
The installer audits complete sudo rules as root; the normal verifier repeats
noninteractive checks and revokes its current sudo authentication context's
cached ticket before checking noninteractive root access. Administrator approval
in another session or a future sudo-policy change is outside this snapshot proof.
Policy changes after installation invalidate the previous
evidence and require a new administrator audit. Python cannot promise perfect
zeroization of immutable/library memory copies; process isolation is essential.
FileVault is recommended for whole-disk theft protection.

The installer uses a clean LaunchDaemon environment and isolated Python mode;
the trading process does not have Broker UID, Keychain access or AES key.
Only the existing four read-only authenticated Demo endpoints remain approved;
no order, cancel, transfer, withdrawal or LIVE route is exposed.

`sudo ./deploy/macos/uninstall.sh` stops/disables services recoverably, retaining
the account, runtime, Keychain, ciphertext and PAPER state. It does not delete
credentials. A service uninstall is not evidence that no previously spawned PAPER
process remains; inspect processes before any subsequent start.
