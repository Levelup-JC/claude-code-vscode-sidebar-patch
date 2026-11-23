#!/bin/bash
# Install a LaunchAgent that re-applies the sidebar patch at login and whenever
# VS Code's extensions.json changes (i.e. after an extension update).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LABEL="local.claude-code-sidebar-patch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/claude-code-sidebar-patch.log"
PY="$(command -v python3)"

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$HERE/reapply.py</string>
  </array>
  <key>WatchPaths</key>
  <array>
    <string>$HOME/.vscode/extensions/extensions.json</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST_EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed: $PLIST"
echo "log: $LOG"
