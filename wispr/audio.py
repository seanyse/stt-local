"""Microphone capture.

By default the input stream is opened when recording starts and closed when it stops, so
macOS shows the microphone-in-use indicator only while you hold the key. Opening costs
~100 ms before the first samples arrive (measured), which is shorter than the usual gap
between pressing the key and starting to speak. `always_open=True` keeps the stream open
permanently instead (zero start-up cost, but the orange mic dot stays on).
"""
from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(self, sample_rate: int = 16000, max_seconds: int = 180, always_open: bool = False):
        self.sample_rate = sample_rate
        self.max_samples = sample_rate * max_seconds
        self.always_open = always_open
        self._chunks: list[np.ndarray] = []
        self._n = 0
        self._recording = False
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        if always_open:
            self._open()

    def _open(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32", blocksize=0, callback=self._callback,
        )
        self._stream.start()

    def _close(self) -> None:
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

    def _callback(self, indata, frames, time_info, status):
        if not self._recording:
            return
        with self._lock:
            if self._n < self.max_samples:
                self._chunks.append(indata[:, 0].copy())
                self._n += frames

    def start(self) -> None:
        with self._lock:
            self._chunks = []
            self._n = 0
            self._recording = True
        self._open()

    @property
    def recording(self) -> bool:
        return self._recording

    def snapshot(self) -> np.ndarray:
        """Everything captured so far in the current recording (copy); recording continues."""
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._chunks)

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False
            audio = np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype=np.float32)
            self._chunks = []
            self._n = 0
        if not self.always_open:
            self._close()
        return audio

    def close(self) -> None:
        self._recording = False
        self._close()


def is_silent(audio: np.ndarray, threshold: float = 0.004) -> bool:
    if audio.size == 0:
        return True
    return float(np.sqrt(np.mean(audio**2))) < threshold
