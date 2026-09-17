# com.lowrisk.paper (macOS LaunchAgent)

Canonical persistent owner of the Low-Risk V2 PAPER runtime on 127.0.0.1:8010.
The DeepSeek key is read from macOS Keychain by `scripts/run_low_risk_paper_secure.sh`;
it is never present in the plist, logs or repository.

## Install / reinstall

    ./scripts/install_low_risk_paper_launchagent.sh

## Install and load / start

    ./scripts/install_low_risk_paper_launchagent.sh --load

## Status

    launchctl print gui/$(id -u)/com.lowrisk.paper

## Restart

    launchctl kickstart -k gui/$(id -u)/com.lowrisk.paper

## Stop

    launchctl kill SIGTERM gui/$(id -u)/com.lowrisk.paper

## Logs

    tail -f "$HOME/Library/Logs/low-risk-paper.stdout.log"
    tail -f "$HOME/Library/Logs/low-risk-paper.stderr.log"

## Health

    curl -fsS http://127.0.0.1:8010/llm/health
    curl -fsS http://127.0.0.1:8010/health

## Uninstall

    launchctl bootout gui/$(id -u)/com.lowrisk.paper
    rm -f "$HOME/Library/LaunchAgents/com.lowrisk.paper.plist"
