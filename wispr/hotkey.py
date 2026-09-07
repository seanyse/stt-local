"""Hold-to-talk hotkey. Quick tap toggles hands-free mode.

If another key is pressed while the hotkey is held (a chord like Ctrl+C), the
recording is cancelled and the tap-to-lock logic is skipped.
"""
from __future__ import annotations

import time
from typing import Callable

from pynput import keyboard


def resolve_key(name: str):
    try:
        return getattr(keyboard.Key, name)
    except AttributeError:
        return keyboard.KeyCode.from_char(name)


class HoldToTalk:
    def __init__(
        self,
        key_name: str,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_cancel: Callable[[], None] = lambda: None,
        tap_seconds: float = 0.25,
    ):
        self.key = resolve_key(key_name)
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cancel = on_cancel
        self.tap_seconds = tap_seconds
        self._down_at: float | None = None
        self._chorded = False
        self._locked = False  # hands-free mode
        self.listener = keyboard.Listener(on_press=self._press, on_release=self._release)

    def _is_key(self, key) -> bool:
        return key == self.key

    def _press(self, key):
        if not self._is_key(key):
            if self._down_at is not None and not self._chorded:
                # Hotkey used as a modifier for something else: abort.
                self._chorded = True
                if not self._locked:
                    self.on_cancel()
            return
        if self._down_at is not None:
            return  # key repeat
        self._down_at = time.monotonic()
        self._chorded = False
        if self._locked:
            return  # release will stop
        self.on_start()

    def _release(self, key):
        if not self._is_key(key) or self._down_at is None:
            return
        held = time.monotonic() - self._down_at
        self._down_at = None
        if self._chorded:
            self._chorded = False
            return  # already cancelled; hands-free lock (if any) stays as is
        if self._locked:
            self._locked = False
            self.on_stop()
            return
        if held < self.tap_seconds:
            self._locked = True  # keep recording until next tap
            return
        self.on_stop()

    def start(self) -> None:
        self.listener.start()

    def stop(self) -> None:
        self.listener.stop()
