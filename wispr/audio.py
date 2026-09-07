"""Always-open microphone stream; buffers samples only while recording."""
from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(self, sample_rate: int = 16000, max_seconds: int = 180):
        self.sample_rate = sample_rate
        self.max_samples = sample_rate * max_seconds
        self._chunks: list[np.ndarray] = []
        self._n = 0
        self._recording = False
        self._lock = threading.Lock()
        # Keeping the stream open avoids ~100ms+ of device start-up latency per utterance.
        self._stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=0,
            callback=self._callback,
        )
        self._stream.start()

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

    @property
    def recording(self) -> bool:
        return self._recording

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks)
            self._chunks = []
            self._n = 0
        return audio

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()


def is_silent(audio: np.ndarray, threshold: float = 0.004) -> bool:
    if audio.size == 0:
        return True
    return float(np.sqrt(np.mean(audio**2))) < threshold
