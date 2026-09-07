"""JSON-lines protocol over stdin/stdout for the native macOS app.

stdin  <- {"cmd": "start"} | {"cmd": "stop"} | {"cmd": "cancel"} | {"cmd": "reload"}
          | {"cmd": "transcribe", "path": "/x.wav"} | {"cmd": "quit"}
stdout -> {"event": "ready"} | {"event": "status", "status": "idle|recording|processing"}
          | {"event": "result", ...history row...} | {"event": "error", "message": "..."}
All human-readable logging goes to stderr.
"""
from __future__ import annotations

import json
import os
import sys
import threading

from .config import Config
from .engine import Engine, log

_out_lock = threading.Lock()


def emit(**obj) -> None:
    with _out_lock:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()


class _Tee:
    def __init__(self, *streams): self.streams = streams
    def write(self, s):
        for st in self.streams: st.write(s)
    def flush(self):
        for st in self.streams: st.flush()


def _app_config() -> Config:
    cfg = Config.load()
    cfg.paste_mode = "none"  # the macOS app inserts text itself (it holds the Accessibility grant)
    return cfg


def main() -> None:
    cfg = _app_config()
    os.makedirs(os.path.expanduser(cfg.log_dir), exist_ok=True)
    sys.stderr = _Tee(sys.__stderr__, open(os.path.join(os.path.expanduser(cfg.log_dir), "engine.log"), "a", buffering=1))
    try:
        engine = Engine(cfg, on_status=lambda s: emit(event="status", status=s), on_result=lambda r: emit(event="result", **r),
                        on_dropped=lambda reason: emit(event="dropped", reason=reason))
    except Exception as e:
        emit(event="error", message=f"{type(e).__name__}: {e}")
        raise
    emit(event="ready")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            emit(event="error", message=f"bad json: {line[:80]}")
            continue
        cmd = msg.get("cmd")
        if cmd == "start":
            engine.start()
        elif cmd == "stop":
            engine.stop()
        elif cmd == "cancel":
            engine.cancel()
        elif cmd == "transcribe":
            engine.transcribe_file(msg["path"])
        elif cmd == "reload":
            engine.reload(_app_config(), on_done=lambda: emit(event="reloaded"))
        elif cmd == "quit":
            break
        else:
            emit(event="error", message=f"unknown cmd {cmd!r}")
    log("[server] stdin closed, exiting")


if __name__ == "__main__":
    main()
