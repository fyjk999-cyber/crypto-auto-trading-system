# LaunchAgent templates

Templates only: do not load into launchd from the repository.
Substitute placeholders before installing into ~/Library/LaunchAgents:

- `__REPO__` -> absolute ML worktree path
- `__PYTHON__` -> absolute canonical venv python path

Install (user level):

    launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.lowrisk.mlcollector.plist 2>/dev/null || true
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lowrisk.mlcollector.plist
    launchctl kickstart -k gui/$(id -u)/com.lowrisk.mlcollector

Collector/trainer templates contain no LLM credentials and no API keys.
