"""Python-only front end: hold the hotkey, talk, release. Menu bar via rumps, or --headless.
The native macOS app in macos/ replaces this with a SwiftUI UI over wispr.server."""
from __future__ import annotations

import os
import sys
import threading
import time

from .config import CONFIG_PATH, Config
from .engine import BUSY, IDLE, REC, Engine, log
from .hotkey import HoldToTalk

ICONS = {IDLE: "🎙", REC: "🔴", BUSY: "⏳"}


class Dictation:
    def __init__(self, cfg: Config, set_status=lambda s: None):
        self.engine = Engine(cfg, on_status=lambda s: set_status(ICONS[s]))
        self.hotkey = HoldToTalk(cfg.hotkey, self.engine.start, self.engine.stop, self.engine.cancel, cfg.tap_seconds)
        self.hotkey.start()
        log(f"[ready] hold {cfg.hotkey} to talk (tap to lock hands-free)")


def run_menubar(cfg: Config):
    import rumps
    from PyObjCTools import AppHelper

    class App(rumps.App):
        def __init__(self):
            super().__init__("⏳", quit_button=None)
            self.status_item = rumps.MenuItem("Loading models…")
            self.menu = [self.status_item, None, rumps.MenuItem("Quit", callback=self.quit)]
            threading.Thread(target=self.boot, daemon=True).start()

        def boot(self):
            try:
                Dictation(cfg, lambda s: AppHelper.callAfter(setattr, self, "title", s))
                AppHelper.callAfter(setattr, self.status_item, "title", f"Hold {cfg.hotkey} to talk · tap to lock")
            except Exception as e:
                AppHelper.callAfter(setattr, self.status_item, "title", f"Error: {e}")
                AppHelper.callAfter(setattr, self, "title", "⚠️")
                raise

        def quit(self, _):
            rumps.quit_application()

    App().run()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cfg = Config.load()
    if not os.path.exists(CONFIG_PATH):
        cfg.save()
    for arg in argv:
        if arg.startswith("--formatter="):
            cfg.formatter = arg.split("=", 1)[1]
        elif arg.startswith("--llm-mode="):
            cfg.llm_mode = arg.split("=", 1)[1]
        elif arg.startswith("--hotkey="):
            cfg.hotkey = arg.split("=", 1)[1]
    if "--headless" in argv:
        Dictation(cfg, lambda s: log(f"[status] {s}"))
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        run_menubar(cfg)


if __name__ == "__main__":
    main()
