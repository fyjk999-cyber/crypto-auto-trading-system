#!/bin/bash
set +x
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Administrator required'; exit 1; }
# Recoverable service retirement only. Never delete vault, Keychain or account.
for task_label in com.crypto-trader.okx-broker com.crypto-trader.okx-paper-launcher; do
  /bin/launchctl bootout "system/$task_label" >/dev/null 2>&1 || true
  task_plist="/Library/LaunchDaemons/$task_label.plist"
  if [[ -f "$task_plist" && ! -L "$task_plist" ]]; then
    /bin/mv -n "$task_plist" "$task_plist.disabled"
  fi
done
echo 'Services stopped. Account, encrypted vault, Keychain, runtime and PAPER data preserved.'
