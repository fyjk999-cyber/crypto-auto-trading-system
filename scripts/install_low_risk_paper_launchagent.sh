#!/usr/bin/env bash
# Install/reinstall the persistent macOS LaunchAgent for the canonical Low-Risk V2
# PAPER runtime. The plist contains no credential: the wrapper loads it from Keychain.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEMPLATE="$ROOT/deploy/launchd/com.lowrisk.paper.plist.template"
AGENTS_DIR="$HOME/Library/LaunchAgents"
LOGS_DIR="$HOME/Library/Logs"
PLIST="$AGENTS_DIR/com.lowrisk.paper.plist"

mkdir -p "$AGENTS_DIR" "$LOGS_DIR"
sed "s|__REPO_ROOT__|$ROOT|g; s|__HOME__|$HOME|g" "$TEMPLATE" > "$PLIST"
chmod 644 "$PLIST"
echo "LAUNCH_AGENT_WRITTEN=$PLIST"
plutil -lint "$PLIST"

if [ "${1:-}" = "--load" ]; then
  launchctl bootout "gui/$(id -u)/com.lowrisk.paper" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  launchctl kickstart "gui/$(id -u)/com.lowrisk.paper" >/dev/null 2>&1 || true
  echo "LAUNCH_AGENT_LOADED=gui/$(id -u)/com.lowrisk.paper"
fi
