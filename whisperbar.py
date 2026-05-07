#!/usr/bin/env python3
"""
WhisperBar — local Whisper dictation in your menu bar.
Left-click to record, click again to stop. Transcript is copied to clipboard.
Right-click for settings and quit.

https://github.com/jasoncypret/whisperbar
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import AppKit
import Foundation
import Quartz
import objc
import cairosvg

# ── Paths ──────────────────────────────────────────────────────────────────────

ASSETS_DIR = Path(__file__).parent / "assets"
CONFIG_DIR = Path.home() / ".config" / "whisperbar"
CONFIG_FILE = CONFIG_DIR / "config.json"

# ── Defaults ───────────────────────────────────────────────────────────────────

DEFAULT_WHISPER_CLI = "/opt/homebrew/bin/whisper-cli"
DEFAULT_SOX = "/opt/homebrew/bin/sox"

MODEL_OPTIONS = {
    "tiny":   "~/.cache/whisper-cpp/ggml-tiny.bin",
    "base":   "~/.cache/whisper-cpp/ggml-base.bin",
    "small":  "~/.cache/whisper-cpp/ggml-small.bin",
    "medium": "~/.cache/whisper-cpp/ggml-medium.bin",
    "large":  "~/.cache/whisper-cpp/ggml-large-v3.bin",
}

# ── Animation constants ────────────────────────────────────────────────────────

ICON_SIZE    = AppKit.NSMakeSize(22, 22)
SPIN_FRAMES  = 12
SPIN_INT     = 0.04
PULSE_FRAMES = 30
PULSE_INT    = 0.05
TOAST_W, TOAST_H = 320, 76
TOAST_MARGIN = 16
TOAST_SECS   = 4.0

STOP_SVG_TPL = """\
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <path d="M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2\
M12,4C16.41,4 20,7.59 20,12C20,16.41 16.41,20 12,20C7.59,20 4,16.41 4,12C4,7.59 7.59,4 12,4\
M9,9V15H15V9" fill="{fill}"/>
</svg>"""

# ── Config helpers ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def detect_whisper_cli() -> str | None:
    for path in [DEFAULT_WHISPER_CLI, "/usr/local/bin/whisper-cli"]:
        if Path(path).exists():
            return path
    result = subprocess.run(["which", "whisper-cli"], capture_output=True, text=True)
    return result.stdout.strip() or None


def detect_sox() -> str | None:
    for path in [DEFAULT_SOX, "/usr/local/bin/sox"]:
        if Path(path).exists():
            return path
    result = subprocess.run(["which", "sox"], capture_output=True, text=True)
    return result.stdout.strip() or None


def find_installed_models() -> list[tuple[str, str]]:
    """Return list of (label, path) for models found on disk."""
    found = []
    for label, raw_path in MODEL_OPTIONS.items():
        path = Path(raw_path).expanduser()
        if path.exists():
            found.append((label, str(path)))
    return found


# ── Image helpers ──────────────────────────────────────────────────────────────

def _svg_to_nsimage(svg_text: str) -> AppKit.NSImage:
    png = cairosvg.svg2png(bytestring=svg_text.encode(), output_width=44, output_height=44)
    data = Foundation.NSData.dataWithBytes_length_(png, len(png))
    img = AppKit.NSImage.alloc().initWithData_(data)
    img.setSize_(ICON_SIZE)
    return img


def _load_icon(name: str, template: bool = True) -> AppKit.NSImage:
    img = AppKit.NSImage.alloc().initWithContentsOfFile_(str(ASSETS_DIR / f"{name}.png"))
    img.setTemplate_(template)
    img.setSize_(ICON_SIZE)
    return img


def _rotated(base: AppKit.NSImage, deg: float) -> AppKit.NSImage:
    sz = base.size()
    out = AppKit.NSImage.alloc().initWithSize_(sz)
    out.lockFocus()
    xf = AppKit.NSAffineTransform.alloc().init()
    xf.translateXBy_yBy_(sz.width / 2, sz.height / 2)
    xf.rotateByDegrees_(deg)
    xf.translateXBy_yBy_(-sz.width / 2, -sz.height / 2)
    xf.concat()
    base.drawAtPoint_fromRect_operation_fraction_(
        AppKit.NSZeroPoint,
        AppKit.NSMakeRect(0, 0, sz.width, sz.height),
        AppKit.NSCompositingOperationSourceOver, 1.0,
    )
    out.unlockFocus()
    out.setTemplate_(True)
    return out


def _build_pulse_frames() -> list:
    frames = []
    for i in range(PULSE_FRAMES):
        s = (math.sin(i / PULSE_FRAMES * 2 * math.pi - math.pi / 2) + 1) / 2
        r, g, b = int(200 + 55 * s), int(20 + 80 * s), int(20 + 10 * s)
        frames.append(_svg_to_nsimage(STOP_SVG_TPL.format(fill=f"rgb({r},{g},{b})")))
    return frames


def _crossfade(btn, img, duration=0.18):
    btn.setWantsLayer_(True)
    t = Quartz.CATransition.alloc().init()
    t.setType_(Quartz.kCATransitionFade)
    t.setDuration_(duration)
    t.setTimingFunction_(
        Quartz.CAMediaTimingFunction.functionWithName_(Quartz.kCAMediaTimingFunctionEaseInEaseOut)
    )
    btn.layer().addAnimation_forKey_(t, "iconSwap")
    btn.setImage_(img)


# ── Setup / first-run ──────────────────────────────────────────────────────────

def run_first_time_setup() -> dict | None:
    """
    Walk the user through setup if config is missing or incomplete.
    Returns a complete config dict, or None if setup was cancelled.
    """
    whisper = detect_whisper_cli()
    sox     = detect_sox()

    if not whisper:
        AppKit.NSRunAlertPanel(
            "WhisperBar — Missing Dependency",
            "whisper-cli was not found.\n\nInstall it with:\n  brew install whisper-cpp\n\nThen relaunch WhisperBar.",
            "OK", None, None,
        )
        return None

    if not sox:
        AppKit.NSRunAlertPanel(
            "WhisperBar — Missing Dependency",
            "sox was not found.\n\nInstall it with:\n  brew install sox\n\nThen relaunch WhisperBar.",
            "OK", None, None,
        )
        return None

    models = find_installed_models()

    if not models:
        # Offer to download a model
        choice = AppKit.NSRunAlertPanel(
            "WhisperBar — No Model Found",
            "No Whisper models were found in ~/.cache/whisper-cpp/.\n\n"
            "Would you like to download the 'medium' model now (~1.5 GB)?\n"
            "Or choose 'Small' for a faster, lighter option (~500 MB).",
            "Download Medium", "Download Small", "Cancel",
        )
        if choice == 0:   # Cancel
            return None
        model_name = "medium" if choice == 1 else "small"
        ok = _download_model(model_name)
        if not ok:
            return None
        models = find_installed_models()

    if len(models) == 1:
        chosen_label, chosen_path = models[0]
    else:
        # Let user pick
        labels = [f"{label}  ({path})" for label, path in models]
        panel = _model_picker_panel(labels)
        idx = panel  # simplified — use first model for now
        chosen_label, chosen_path = models[0]

    cfg = {
        "whisper_cli": whisper,
        "sox": sox,
        "model": chosen_path,
        "model_name": chosen_label,
    }
    save_config(cfg)
    return cfg


def _download_model(name: str) -> bool:
    """Download a whisper-cpp model using the bundled downloader script."""
    download_script = Path("/opt/homebrew/share/whisper-cpp/models/download-ggml-model.sh")
    if not download_script.exists():
        AppKit.NSRunAlertPanel(
            "WhisperBar",
            f"Could not find the whisper-cpp model downloader.\n"
            f"Please download manually:\n"
            f"  cd ~/.cache/whisper-cpp && bash {download_script} {name}",
            "OK", None, None,
        )
        return False

    cache = Path.home() / ".cache" / "whisper-cpp"
    cache.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["bash", str(download_script), name],
        cwd=str(cache),
    )
    return result.returncode == 0


# ── Main app ───────────────────────────────────────────────────────────────────

class WhisperBarApp(AppKit.NSObject):

    def applicationDidFinishLaunching_(self, _n):
        self._recording   = False
        self._processing  = False   # True while transcription is in-flight
        self._record_proc = None
        self._temp_wav    = None
        self._spin_angle  = 0
        self._spin_timer  = None
        self._pulse_idx   = 0
        self._pulse_timer = None
        self._toast_win   = None
        self._toast_timer = None

        # Load or create config
        cfg = load_config()
        if not cfg.get("whisper_cli") or not cfg.get("model"):
            cfg = run_first_time_setup()
            if cfg is None:
                AppKit.NSApp.terminate_(None)
                return

        self._cfg = cfg

        # Pre-generate animation frames
        self._pulse_frames = _build_pulse_frames()

        self._icon_idle = _load_icon("mic")
        self._icon_load = _load_icon("mic-loading")

        # Status item
        self._item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength
        )
        btn = self._item.button()
        btn.setImage_(self._icon_idle)
        btn.setToolTip_("WhisperBar — click to record")
        btn.setAction_("handleClick:")
        btn.setTarget_(self)
        btn.sendActionOn_(AppKit.NSEventMaskLeftMouseDown | AppKit.NSEventMaskRightMouseDown)

        self._build_menu()

    @objc.python_method
    def _build_menu(self):
        menu = AppKit.NSMenu.alloc().init()

        # Last transcript
        self._last_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Last: —", None, ""
        )
        self._last_item.setEnabled_(False)
        menu.addItem_(self._last_item)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Settings submenu
        settings_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings", None, ""
        )
        sub = AppKit.NSMenu.alloc().init()

        model_label = self._cfg.get("model_name", "unknown")
        model_display = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"Model: {model_label}", None, ""
        )
        model_display.setEnabled_(False)
        sub.addItem_(model_display)

        sub.addItem_(AppKit.NSMenuItem.separatorItem())

        for label in MODEL_OPTIONS:
            item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                f"Switch to {label}", "switchModel:", ""
            )
            item.setRepresentedObject_(label)
            item.setTarget_(self)
            sub.addItem_(item)

        sub.addItem_(AppKit.NSMenuItem.separatorItem())
        open_cfg = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open config file", "openConfig:", ""
        )
        open_cfg.setTarget_(self)
        sub.addItem_(open_cfg)

        settings_item.setSubmenu_(sub)
        menu.addItem_(settings_item)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        menu.addItem_(
            AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit WhisperBar", "terminate:", "q")
        )
        self._menu = menu

    # ── ObjC actions ──────────────────────────────────────────────────────────

    def handleClick_(self, _s):
        ev = AppKit.NSApp.currentEvent()
        right = (
            ev.type() == AppKit.NSEventTypeRightMouseDown
            or bool(ev.modifierFlags() & AppKit.NSEventModifierFlagControl)
        )
        if right:
            self._item.popUpStatusItemMenu_(self._menu)
        elif self._processing:
            pass  # ignore clicks while transcription is in-flight
        elif self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def pulseTick_(self, _t):
        self._item.button().setImage_(self._pulse_frames[self._pulse_idx % PULSE_FRAMES])
        self._pulse_idx += 1

    def spinTick_(self, _t):
        self._spin_angle = (self._spin_angle + 360 / SPIN_FRAMES) % 360
        self._item.button().setImage_(_rotated(self._icon_load, self._spin_angle))

    def dismissToast_(self, _t):
        self._toast_timer = None
        win = self._toast_win
        if not win:
            return
        self._toast_win = None

        def fade(ctx):
            ctx.setDuration_(0.3)

        def remove():
            win.orderOut_(None)

        AppKit.NSAnimationContext.runAnimationGroup_completionHandler_(fade, remove)
        win.animator().setAlphaValue_(0.0)

    def switchModel_(self, sender):
        label = sender.representedObject()
        path = str(Path(MODEL_OPTIONS[label]).expanduser())
        if not Path(path).exists():
            AppKit.NSRunAlertPanel(
                "WhisperBar",
                f"Model '{label}' not found at:\n{path}\n\nDownload it with:\n  brew install whisper-cpp",
                "OK", None, None,
            )
            return
        self._cfg["model"] = path
        self._cfg["model_name"] = label
        save_config(self._cfg)
        self._build_menu()

    def openConfig_(self, _s):
        subprocess.run(["open", str(CONFIG_FILE)])

    # ── Python helpers ─────────────────────────────────────────────────────────

    @objc.python_method
    def _start_recording(self):
        self._recording = True
        self._pulse_idx = 0
        _crossfade(self._item.button(), self._pulse_frames[0])
        self._pulse_timer = Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            PULSE_INT, self, "pulseTick:", None, True
        )
        self._item.button().setToolTip_("Recording… click to stop")
        self._temp_wav = tempfile.mktemp(suffix=".wav")
        self._record_proc = subprocess.Popen(
            [self._cfg["sox"], "-d", self._temp_wav, "rate", "16000", "channels", "1"],
            stderr=subprocess.DEVNULL,
        )

    @objc.python_method
    def _stop_recording(self):
        self._recording  = False
        self._processing = True
        if self._pulse_timer:
            self._pulse_timer.invalidate()
            self._pulse_timer = None
        if self._record_proc:
            self._record_proc.terminate()
            self._record_proc.wait()
        self._spin_angle = 0
        _crossfade(self._item.button(), self._icon_load)
        self._spin_timer = Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            SPIN_INT, self, "spinTick:", None, True
        )
        self._item.button().setToolTip_("Transcribing…")
        threading.Thread(target=self._transcribe, daemon=True).start()

    @objc.python_method
    def _transcribe(self):
        try:
            r = subprocess.run(
                [self._cfg["whisper_cli"], "-m", self._cfg["model"],
                 "-f", self._temp_wav, "--no-timestamps", "-nt"],
                capture_output=True, text=True, timeout=120,
            )
            text = r.stdout.strip() or r.stderr.strip() or "(no speech detected)"
        except Exception as exc:
            text = f"(error: {exc})"
        finally:
            try:
                os.unlink(self._temp_wav)
            except OSError:
                pass

        subprocess.run(["pbcopy"], input=text.encode(), check=False)
        Foundation.NSOperationQueue.mainQueue().addOperationWithBlock_(lambda: self._done(text))

    @objc.python_method
    def _done(self, text):
        self._processing = False
        if self._spin_timer:
            self._spin_timer.invalidate()
            self._spin_timer = None
        _crossfade(self._item.button(), self._icon_idle)
        self._item.button().setToolTip_("WhisperBar — click to record")
        self._last_item.setTitle_(
            "Last: " + text[:80] + ("…" if len(text) > 80 else "")
        )
        self._show_toast(text)

    @objc.python_method
    def _show_toast(self, text):
        try:
            if self._toast_timer:
                self._toast_timer.invalidate()
                self._toast_timer = None
            if self._toast_win:
                self._toast_win.orderOut_(None)
                self._toast_win = None

            screen = AppKit.NSScreen.screens()[0]
            sf = screen.frame()
            vf = screen.visibleFrame()
            menu_bar_h = sf.size.height - (vf.origin.y + vf.size.height)
            x = sf.origin.x + sf.size.width - TOAST_W - TOAST_MARGIN
            y = sf.origin.y + sf.size.height - menu_bar_h - TOAST_H - TOAST_MARGIN

            win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                AppKit.NSMakeRect(x, y + 12, TOAST_W, TOAST_H),
                AppKit.NSWindowStyleMaskBorderless,
                AppKit.NSBackingStoreBuffered, False,
            )
            win.setLevel_(AppKit.NSFloatingWindowLevel)
            win.setOpaque_(False)
            win.setBackgroundColor_(AppKit.NSColor.clearColor())
            win.setHasShadow_(True)
            win.setIgnoresMouseEvents_(True)
            win.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | AppKit.NSWindowCollectionBehaviorStationary
            )

            blur = AppKit.NSVisualEffectView.alloc().initWithFrame_(
                AppKit.NSMakeRect(0, 0, TOAST_W, TOAST_H)
            )
            blur.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
            blur.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
            blur.setState_(AppKit.NSVisualEffectStateActive)
            blur.setWantsLayer_(True)
            blur.layer().setCornerRadius_(12.0)
            blur.layer().setMasksToBounds_(True)
            blur.layer().setShadowColor_(
                AppKit.NSColor.blackColor().colorWithAlphaComponent_(0.5).CGColor()
            )
            blur.layer().setShadowOpacity_(1.0)
            blur.layer().setShadowOffset_(AppKit.NSMakeSize(0, -4))
            blur.layer().setShadowRadius_(16.0)
            win.setContentView_(blur)

            title_f = AppKit.NSTextField.labelWithString_("Copied to clipboard")
            title_f.setFrame_(AppKit.NSMakeRect(16, TOAST_H - 30, TOAST_W - 32, 18))
            title_f.setTextColor_(AppKit.NSColor.whiteColor())
            title_f.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
            blur.addSubview_(title_f)

            body_f = AppKit.NSTextField.labelWithString_(
                text[:100] + ("…" if len(text) > 100 else "")
            )
            body_f.setFrame_(AppKit.NSMakeRect(16, 12, TOAST_W - 32, 28))
            body_f.setTextColor_(AppKit.NSColor.colorWithWhite_alpha_(0.75, 1.0))
            body_f.setFont_(AppKit.NSFont.systemFontOfSize_(11))
            body_f.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
            blur.addSubview_(body_f)

            win.setAlphaValue_(0.0)
            win.orderFrontRegardless()
            self._toast_win = win

            def slide_in(ctx):
                ctx.setDuration_(0.35)
                ctx.setTimingFunction_(
                    Quartz.CAMediaTimingFunction.functionWithName_(Quartz.kCAMediaTimingFunctionEaseOut)
                )

            AppKit.NSAnimationContext.runAnimationGroup_completionHandler_(slide_in, None)
            win.animator().setAlphaValue_(1.0)
            win.animator().setFrame_display_animate_(
                AppKit.NSMakeRect(x, y, TOAST_W, TOAST_H), True, True
            )

            self._toast_timer = Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                TOAST_SECS, self, "dismissToast:", None, False
            )
        except Exception as e:
            print(f"[whisperbar] toast error: {e}", flush=True)
            import traceback; traceback.print_exc()


def main():
    app = AppKit.NSApplication.sharedApplication()
    delegate = WhisperBarApp.alloc().init()
    app.setDelegate_(delegate)
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    app.run()


if __name__ == "__main__":
    main()
