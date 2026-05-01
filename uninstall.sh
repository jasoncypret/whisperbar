#!/usr/bin/env bash
set -euo pipefail

PLIST_LABEL="com.whisperbar.app"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

echo ""
echo "  WhisperBar — Uninstall"
echo "  ──────────────────────"
echo ""

launchctl bootout "gui/$(id -u)/$PLIST_LABEL" 2>/dev/null && echo "  ✓ Stopped WhisperBar" || true
[ -f "$PLIST_PATH" ] && rm "$PLIST_PATH" && echo "  ✓ Removed LaunchAgent"

read -rp "  Remove config and logs? (~/.config/whisperbar) [y/N]: " REMOVE_CFG
if [[ "${REMOVE_CFG,,}" == "y" ]]; then
  rm -rf "$HOME/.config/whisperbar"
  echo "  ✓ Removed config"
fi

echo ""
echo "  WhisperBar uninstalled. Whisper models in ~/.cache/whisper-cpp were kept."
echo ""
