#!/usr/bin/env bash
set -euo pipefail

PLIST_LABEL="com.whisperbar.app"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/opt/homebrew/bin/python3.12"
LOG_DIR="$HOME/.config/whisperbar/logs"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}▶ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠ $*${NC}"; }
error() { echo -e "${RED}✗ $*${NC}"; exit 1; }

echo ""
echo "  WhisperBar — Install"
echo "  ───────────────────────────"
echo ""

# ── Homebrew ──────────────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  error "Homebrew not found. Install it from https://brew.sh then re-run this script."
fi

# ── Dependencies ──────────────────────────────────────────────────────────────
info "Checking dependencies…"

if ! command -v whisper-cli &>/dev/null; then
  warn "whisper-cli not found — installing whisper-cpp via Homebrew…"
  brew install whisper-cpp
fi

if ! command -v sox &>/dev/null; then
  warn "sox not found — installing via Homebrew…"
  brew install sox
fi

if ! "$PYTHON" --version &>/dev/null; then
  warn "Python 3.12 not found — installing via Homebrew…"
  brew install python@3.12
fi

# ── Python packages ───────────────────────────────────────────────────────────
info "Installing Python dependencies…"
"$PYTHON" -m pip install --quiet --break-system-packages \
  pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz cairosvg

# ── Whisper model ─────────────────────────────────────────────────────────────
MODEL_DIR="$HOME/.cache/whisper-cpp"
mkdir -p "$MODEL_DIR"

EXISTING_MODELS=$(ls "$MODEL_DIR"/ggml-*.bin 2>/dev/null | wc -l | tr -d ' ')

if [ "$EXISTING_MODELS" -eq 0 ]; then
  echo ""
  echo "  No Whisper models found. Choose one to download:"
  echo ""
  echo "    1) tiny    (~75 MB)   — fastest, lower accuracy"
  echo "    2) base    (~142 MB)  — fast, decent accuracy"
  echo "    3) small   (~466 MB)  — good balance"
  echo "    4) medium  (~1.5 GB)  — recommended, high accuracy"
  echo "    5) Skip    — I'll set up the model manually"
  echo ""
  read -rp "  Choice [4]: " MODEL_CHOICE
  MODEL_CHOICE="${MODEL_CHOICE:-4}"

  case "$MODEL_CHOICE" in
    1) MODEL_NAME="tiny"   ;;
    2) MODEL_NAME="base"   ;;
    3) MODEL_NAME="small"  ;;
    4) MODEL_NAME="medium" ;;
    5) MODEL_NAME=""       ;;
    *) MODEL_NAME="medium" ;;
  esac

  if [ -n "$MODEL_NAME" ]; then
    DOWNLOADER="$(brew --prefix whisper-cpp)/share/whisper-cpp/models/download-ggml-model.sh"
    if [ -f "$DOWNLOADER" ]; then
      info "Downloading $MODEL_NAME model…"
      cd "$MODEL_DIR" && bash "$DOWNLOADER" "$MODEL_NAME"
    else
      warn "Downloader not found at $DOWNLOADER"
      warn "Download manually: https://huggingface.co/ggerganov/whisper.cpp"
    fi
  fi
else
  info "Found $EXISTING_MODELS model(s) in $MODEL_DIR — skipping download."
fi

# ── LaunchAgent ───────────────────────────────────────────────────────────────
info "Installing LaunchAgent…"
mkdir -p "$LOG_DIR"

# Stop existing instance if running
launchctl bootout "gui/$(id -u)/$PLIST_LABEL" 2>/dev/null || true

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$INSTALL_DIR/whisperbar.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/whisperbar.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/whisperbar.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
PLIST

launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo ""
echo "  ✓ WhisperBar installed!"
echo ""
echo "  The mic icon should appear in your menu bar shortly."
echo "  Left-click to record, right-click for settings."
echo ""
echo "  Logs: $LOG_DIR/whisperbar.log"
echo "  Config: $HOME/.config/whisperbar/config.json"
echo ""
