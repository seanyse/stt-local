"""The dictation engine: mic -> speech-to-text -> cleanup -> paste, on one worker thread.

Used by both the Python menu-bar app (wispr.app) and the JSON-lines server that
the native macOS app talks to (wispr.server). MLX streams are thread-local, so
every model call happens on the single worker thread.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from datetime import datetime

import numpy as np

from .audio import Recorder, is_silent
from .config import Config
from .formatter import DEFAULT_TRIGGERS, build_formatter, format_transcript
from .inject import insert_text
from .stt import SpeechToText

IDLE, REC, BUSY = "idle", "recording", "processing"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


class Engine:
    def __init__(self, cfg: Config, on_status=lambda s: None, on_result=lambda r: None):
        self.cfg = cfg
        self.on_status = on_status
        self.on_result = on_result
        self.jobs: queue.Queue = queue.Queue()
        self.ready = threading.Event()
        self.error: Exception | None = None
        os.makedirs(os.path.expanduser(cfg.log_dir), exist_ok=True)

        self.recorder = Recorder(cfg.sample_rate, cfg.max_seconds)
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()
        self.ready.wait()
        if self.error:
            raise self.error
        self.on_status(IDLE)

    # -- public, callable from any thread --------------------------------------------
    def start(self) -> None:
        self.recorder.start()
        self.on_status(REC)
        if self.cfg.warm_on_start:
            self.jobs.put(("warm", None))  # spin the GPU up while the user is talking

    def stop(self) -> None:
        audio = self.recorder.stop()
        self.on_status(BUSY)
        self.jobs.put(("audio", audio))

    def cancel(self) -> None:
        self.recorder.stop()
        self.on_status(IDLE)

    def transcribe_file(self, path: str) -> None:
        """Debug helper: run the pipeline on a wav (16 kHz mono int16) instead of the mic."""
        import wave

        with wave.open(path) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        self.on_status(BUSY)
        self.jobs.put(("audio", pcm.astype(np.float32) / 32768.0))

    def reload(self, cfg: Config, on_done=lambda: None) -> None:
        self.jobs.put(("reload", (cfg, on_done)))

    # -- worker ------------------------------------------------------------------------
    def _load(self) -> None:
        t = time.perf_counter()
        self.stt = SpeechToText(self.cfg.stt_model, self.cfg.vocabulary)
        log(f"[init] speech-to-text ready in {time.perf_counter() - t:.1f}s")
        t = time.perf_counter()
        self.formatter = build_formatter(self.cfg)
        log(f"[init] formatter '{self.formatter.name}' ready in {time.perf_counter() - t:.1f}s")

    def _worker(self) -> None:
        try:
            self._load()
        except Exception as e:
            self.error = e
            self.ready.set()
            return
        self.ready.set()
        while True:
            kind, payload = self.jobs.get()
            try:
                if kind == "audio":
                    self._process(payload)
                elif kind == "warm":
                    if self.recorder.recording:
                        self.stt.transcribe(np.zeros(self.stt.sample_rate, dtype=np.float32))
                elif kind == "reload":
                    cfg, on_done = payload
                    old = self.cfg
                    self.cfg = cfg
                    if cfg.stt_model != old.stt_model or cfg.vocabulary != old.vocabulary:
                        self.stt = SpeechToText(cfg.stt_model, cfg.vocabulary)
                    if (cfg.formatter, cfg.llm_model, cfg.claude_model, cfg.vocabulary) != (
                        old.formatter, old.llm_model, old.claude_model, old.vocabulary
                    ):
                        self.formatter = build_formatter(cfg)
                    log("[reload] config applied")
                    on_done()
            except Exception as e:
                log(f"[error] {type(e).__name__}: {e}")
            finally:
                if kind != "warm" and not self.recorder.recording:
                    self.on_status(IDLE)

    def _process(self, audio: np.ndarray) -> None:
        seconds = len(audio) / self.cfg.sample_rate
        if seconds < 0.3 or is_silent(audio):
            return
        t0 = time.perf_counter()
        raw = self.stt.transcribe(audio)
        t_stt = time.perf_counter() - t0
        if not raw:
            return
        text, t_fmt = format_transcript(
            self.formatter, raw, self.cfg.min_words_for_llm,
            self.cfg.llm_mode, DEFAULT_TRIGGERS + list(self.cfg.extra_triggers), self.cfg.replacements,
        )
        t1 = time.perf_counter()
        insert_text(text, self.cfg.paste_mode)
        t_paste = time.perf_counter() - t1
        total = time.perf_counter() - t0
        log(f"[{seconds:.1f}s audio] stt {t_stt*1000:.0f}ms + format {t_fmt*1000:.0f}ms + paste {t_paste*1000:.0f}ms = {total*1000:.0f}ms")
        log(f"  raw:   {raw}\n  clean: {text}")
        wav = self._save_audio(audio) if self.cfg.save_audio else None
        row = dict(
            ts=datetime.now().isoformat(timespec="seconds"), audio_seconds=round(seconds, 2), raw=raw, clean=text,
            stt_ms=round(t_stt * 1000), format_ms=round(t_fmt * 1000), total_ms=round(total * 1000),
            formatter=self.formatter.name, stt_model=self.cfg.stt_model, wav=wav,
        )
        with open(os.path.join(os.path.expanduser(self.cfg.log_dir), "history.jsonl"), "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.on_result(row)

    def _save_audio(self, audio: np.ndarray) -> str:
        import wave

        path = os.path.join(os.path.expanduser(self.cfg.log_dir), datetime.now().strftime("%Y%m%d-%H%M%S") + ".wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.cfg.sample_rate)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        return path
