"""Insert text into whatever app has keyboard focus."""
from __future__ import annotations

import threading
import time

import Quartz
from AppKit import NSPasteboard, NSPasteboardTypeString

KVK_V = 9  # kVK_ANSI_V


def _post_key(keycode: int, flags: int = 0) -> None:
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(src, keycode, down)
        Quartz.CGEventSetFlags(ev, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def paste_via_clipboard(text: str, restore_after: float = 0.6) -> None:
    pb = NSPasteboard.generalPasteboard()
    previous = pb.stringForType_(NSPasteboardTypeString)
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)
    _post_key(KVK_V, Quartz.kCGEventFlagMaskCommand)

    if previous is not None:
        def restore():
            # Only restore if nobody else has changed the clipboard in the meantime.
            if pb.stringForType_(NSPasteboardTypeString) == text:
                pb.clearContents()
                pb.setString_forType_(previous, NSPasteboardTypeString)

        threading.Timer(restore_after, restore).start()


def type_text(text: str, chunk: int = 20) -> None:
    """Synthesize unicode keystrokes; leaves the clipboard untouched."""
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for i in range(0, len(text), chunk):
        piece = text[i : i + chunk]
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(src, 0, down)
            Quartz.CGEventKeyboardSetUnicodeString(ev, len(piece), piece)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.005)


def copy_only(text: str) -> None:
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)


def insert_text(text: str, mode: str = "clipboard") -> None:
    """mode: clipboard (paste + restore), type (keystrokes), copy (clipboard only), none."""
    if not text or mode == "none":
        return
    if mode == "type":
        type_text(text)
    elif mode == "copy":
        copy_only(text)
    else:
        paste_via_clipboard(text)
