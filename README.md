# WhisperBar

Local Whisper dictation in your macOS menu bar. Click to record, transcript copies to clipboard — no cloud, no subscription.

![WhisperBar demo](assets/demo.gif)

## Features

- **One-click recording** — left-click the mic to start, click again to stop
- **Fully local** — uses [whisper.cpp](https://github.com/ggerganov/whisper.cpp) on your machine, nothing sent to any server
- **Visual feedback** — pulsing red animation while recording, spinning indicator while transcribing
- **Toast notification** — frosted-glass popup shows the transcript when done
- **Model switching** — right-click → Settings to switch between tiny/base/small/medium/large models
- **Auto-start** — installs as a LaunchAgent, runs at login

## Requirements

- macOS 13 Ventura or later
- [Homebrew](https://brew.sh)
- ~500 MB–1.5 GB disk space for a Whisper model

## Install

```bash
git clone https://github.com/jasoncypret/whisperbar.git
cd whisperbar
chmod +x install.sh
./install.sh
```

The install script will:
1. Install `whisper-cpp` and `sox` via Homebrew if missing
2. Offer to download a Whisper model (tiny / base / small / medium)
3. Install Python dependencies
4. Register WhisperBar as a Login Item (LaunchAgent)

The mic icon appears in your menu bar when it's ready.

## Usage

| Action | Result |
|---|---|
| Left-click mic | Start recording |
| Left-click stop circle | Stop recording + transcribe |
| Right-click | Settings, last transcript, quit |

Transcript is automatically copied to your clipboard. A toast notification appears in the top-right corner when done.

## Model Guide

| Model | Size | Speed | Accuracy |
|---|---|---|---|
| tiny | 75 MB | Very fast | Basic |
| base | 142 MB | Fast | Decent |
| small | 466 MB | Good | Good |
| **medium** | 1.5 GB | Moderate | **Recommended** |
| large | 3 GB | Slow | Best |

Switch models anytime via right-click → Settings → Switch to…

## Config

Settings are stored in `~/.config/whisperbar/config.json`:

```json
{
  "whisper_cli": "/opt/homebrew/bin/whisper-cli",
  "sox": "/opt/homebrew/bin/sox",
  "model": "/Users/you/.cache/whisper-cpp/ggml-medium.bin",
  "model_name": "medium"
}
```

## Uninstall

```bash
./uninstall.sh
```

## Tech Stack

- Python 3.12 + PyObjC (AppKit, Quartz)
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) via `whisper-cli`
- [sox](https://sox.sourceforge.net) for audio capture
- [cairosvg](https://cairosvg.org) for icon rendering

## License

MIT — free to use, modify, and distribute.
