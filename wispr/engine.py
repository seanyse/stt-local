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


def _find_pause_cut(seg: np.ndarray, sr: int, min_len: int, pause_s: float = 1.0, hop_s: float = 0.05,
                    resume_s: float = 0.4) -> int | None:
    """Sample index in `seg` at the middle of the last quiet stretch of >= pause_s that starts
    after min_len samples AND is followed by >= resume_s of speech (so it is a real gap between
    phrases, not a hesitation still in progress). Accuracy note: cutting inside a sentence
    costs far more than the latency saved, so the defaults are deliberately conservative."""
    hop = int(hop_s * sr)
    n = len(seg) // hop
    if n < 4:
        return None
    frames = seg[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    floor = float(np.percentile(rms, 10))
    loud = float(np.percentile(rms, 90))
    thresh = max(0.0025, min(3.0 * floor, 0.15 * loud))
    quiet = rms < thresh
    need = int(pause_s / hop_s)
    resume = int(resume_s / hop_s)
    best = None
    i = 0
    while i < n:
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j < n and quiet[j]:
            j += 1
        run = j - i
        if run >= need and i * hop >= min_len:
            after = quiet[j : j + resume]
            if len(after) >= resume and not after.any():
                best = (i + run // 2) * hop
        i = j
    return best


class Engine:
    def __init__(self, cfg: Config, on_status=lambda s: None, on_result=lambda r: None, on_dropped=lambda reason: None):
        self.cfg = cfg
        self.on_status = on_status
        self.on_result = on_result
        self.on_dropped = on_dropped
        self.jobs: queue.Queue = queue.Queue()
        self.ready = threading.Event()
        self.error: Exception | None = None
        os.makedirs(os.path.expanduser(cfg.log_dir), exist_ok=True)

        self.recorder = Recorder(cfg.sample_rate, cfg.max_seconds)
        # Per-utterance state for transcribe-while-talking (see _segmenter).
        self._utt = 0             # utterance id; jobs from an older utterance are ignored
        self._seg_lock = threading.Lock()
        self._consumed = 0        # samples already handed to the worker
        self._segments: list[str] = []
        self._seg_ms = 0.0
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()
        self.ready.wait()
        if self.error:
            raise self.error
        self.on_status(IDLE)

    # -- public, callable from any thread --------------------------------------------
    def start(self) -> None:
        with self._seg_lock:
            self._utt += 1
            self._consumed = 0
            self._segments = []
            self._seg_ms = 0.0
            utt = self._utt
        self.recorder.start()
        self.on_status(REC)
        if self.cfg.segment_while_recording:
            threading.Thread(target=self._segmenter, args=(utt,), daemon=True).start()
        elif self.cfg.warm_on_start:
            self.jobs.put(("warm", utt, None))  # spin the GPU up while the user is talking

    def stop(self) -> None:
        with self._seg_lock:
            audio = self.recorder.stop()
            utt = self._utt
            tail = audio[self._consumed:]
        self.on_status(BUSY)
        self.jobs.put(("final", utt, (audio, tail)))

    def cancel(self) -> None:
        with self._seg_lock:
            self.recorder.stop()
            self._utt += 1  # orphan any queued segment jobs
        self.on_status(IDLE)

    # -- transcribe while talking -------------------------------------------------------
    def _segmenter(self, utt: int) -> None:
        """Every 250 ms, look at the audio captured so far; whenever a phrase has ended
        (>= 0.6 s pause) hand it to the worker. Also cuts at 25 s if the speaker never pauses."""
        sr = self.cfg.sample_rate
        min_len, max_len = 8 * sr, 28 * sr
        while True:
            time.sleep(0.25)
            with self._seg_lock:
                if utt != self._utt or not self.recorder.recording:
                    return
                audio = self.recorder.snapshot()
                seg = audio[self._consumed:]
                if len(seg) < min_len:
                    continue
                cut = _find_pause_cut(seg, sr, min_len)
                if cut is None and len(seg) >= max_len:
                    cut = max_len
                if cut is None:
                    continue
                self.jobs.put(("segment", utt, seg[:cut].copy()))
                self._consumed += cut

    def transcribe_file(self, path: str) -> None:
        """Debug helper: run the pipeline on a wav (16 kHz mono int16) instead of the mic."""
        import wave

        with wave.open(path) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        audio = pcm.astype(np.float32) / 32768.0
        with self._seg_lock:
            self._utt += 1
            self._segments = []
            self._seg_ms = 0.0
            utt = self._utt
        self.on_status(BUSY)
        self.jobs.put(("final", utt, (audio, audio)))

    def reload(self, cfg: Config, on_done=lambda: None) -> None:
        self.jobs.put(("reload", 0, (cfg, on_done)))

    # -- worker ------------------------------------------------------------------------
    def _load(self) -> None:
        t = time.perf_counter()
        self.stt = SpeechToText(self.cfg.stt_model, self.cfg.vocabulary, self.cfg.language, self.cfg.stt_quant_bits)
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
            kind, utt, payload = self.jobs.get()
            if kind in ("segment", "final", "warm") and utt != self._utt:
                continue  # cancelled or superseded utterance
            try:
                if kind == "segment":
                    t = time.perf_counter()
                    text = "" if is_silent(payload) else self.stt.transcribe(payload, context=" ".join(self._segments))
                    self._seg_ms += (time.perf_counter() - t) * 1000
                    if text:
                        self._segments.append(text)
                elif kind == "final":
                    audio, tail = payload
                    self._process(audio, tail)
                elif kind == "warm":
                    if self.recorder.recording:
                        self.stt.transcribe(np.zeros(self.stt.sample_rate, dtype=np.float32))
                elif kind == "reload":
                    cfg, on_done = payload
                    old = self.cfg
                    self.cfg = cfg
                    if (cfg.stt_model, cfg.vocabulary, cfg.language, cfg.stt_quant_bits) != (
                        old.stt_model, old.vocabulary, old.language, old.stt_quant_bits
                    ):
                        self.stt = None
                        import gc; gc.collect(); import mlx.core as mx; mx.clear_cache()
                        self.stt = SpeechToText(cfg.stt_model, cfg.vocabulary, cfg.language, cfg.stt_quant_bits)
                    if (cfg.formatter, cfg.llm_model, cfg.claude_model, cfg.vocabulary) != (
                        old.formatter, old.llm_model, old.claude_model, old.vocabulary
                    ):
                        self.formatter = build_formatter(cfg)
                    log("[reload] config applied")
                    on_done()
            except Exception as e:
                log(f"[error] {type(e).__name__}: {e}")
            finally:
                if kind in ("final", "reload") and not self.recorder.recording:
                    self.on_status(IDLE)

    def _process(self, audio: np.ndarray, tail: np.ndarray) -> None:
        """`audio` is the whole recording (for the wav); `tail` is the part not yet transcribed."""
        seconds = len(audio) / self.cfg.sample_rate
        if seconds < 0.3 or (is_silent(audio) and not self._segments):
            rms = float(np.sqrt(np.mean(audio**2))) if audio.size else 0.0
            log(f"[dropped] {seconds:.1f}s of audio, rms {rms:.4f} (silent or too short)")
            self.on_dropped("silent" if seconds >= 0.3 else "too short")
            return
        t0 = time.perf_counter()
        tail_text = "" if is_silent(tail) else self.stt.transcribe(tail, context=" ".join(self._segments))
        t_stt = time.perf_counter() - t0
        raw = " ".join(self._segments + ([tail_text] if tail_text else [])).strip()
        if self._segments:
            log(f"[segments] {len(self._segments)} phrase(s) transcribed while talking ({self._seg_ms:.0f}ms), tail {len(tail)/self.cfg.sample_rate:.1f}s")
        if not raw:
            log(f"[dropped] {seconds:.1f}s of audio produced no text ({t_stt*1000:.0f}ms)")
            self.on_dropped("no text")
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
            segments=len(self._segments), background_stt_ms=round(self._seg_ms),
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
