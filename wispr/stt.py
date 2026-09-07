"""Speech-to-text on Apple Silicon via MLX.

Two engines, chosen by the model id:
  - Parakeet TDT (default): ~150 ms for 5 s of audio, good punctuation.
  - Whisper (any id containing "whisper"): ~5x slower, but accepts a text prompt,
    so the `vocabulary` list biases it toward your jargon and names.
"""
from __future__ import annotations

import time

import mlx.core as mx
import numpy as np


# Whisper emits these on silence or noise; drop them when the clip is short.
HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching", "you", "bye", "so", "the end", "subtitles by the amara.org community"}


class SpeechToText:
    def __init__(self, model_id: str = "mlx-community/parakeet-tdt-0.6b-v3", vocabulary: list[str] | None = None):
        self.model_id = model_id
        self.sample_rate = 16000
        self.prompt = ", ".join(vocabulary) + "." if vocabulary else None
        if "whisper" in model_id.lower():
            import mlx_whisper  # noqa: F401  (imported here so Parakeet users don't need it)

            self.engine = "whisper"
            self.model = None
        else:
            from parakeet_mlx import from_pretrained

            self.engine = "parakeet"
            self.model = from_pretrained(model_id)
            self.sample_rate = self.model.preprocessor_config.sample_rate
        self.warmup()

    def warmup(self) -> None:
        # First call compiles Metal kernels / loads weights; do it before the user talks.
        self.transcribe(np.zeros(self.sample_rate, dtype=np.float32))

    def transcribe(self, audio: np.ndarray) -> str:
        """audio: float32 mono at self.sample_rate."""
        if audio.size < self.sample_rate // 10:
            return ""
        try:
            return self._transcribe(audio)
        finally:
            # MLX keeps freed buffers cached (≈1 GB after Whisper). Give them back so the
            # idle engine is mostly just weights and less likely to be paged out.
            mx.clear_cache()

    def _transcribe(self, audio: np.ndarray) -> str:
        if self.engine == "whisper":
            import mlx_whisper

            out = mlx_whisper.transcribe(
                audio.astype(np.float32), path_or_hf_repo=self.model_id, initial_prompt=self.prompt, fp16=True
            )
            text = out["text"].strip()
            if len(audio) < self.sample_rate * 4 and text.lower().strip(".!,") in HALLUCINATIONS:
                return ""
            return text

        from parakeet_mlx.audio import get_logmel

        mel = get_logmel(mx.array(audio.astype(np.float32)), self.model.preprocessor_config)
        return self.model.generate(mel)[0].text.strip()


if __name__ == "__main__":
    import sys
    import wave

    stt = SpeechToText(sys.argv[2] if len(sys.argv) > 2 else "mlx-community/parakeet-tdt-0.6b-v3")
    with wave.open(sys.argv[1]) as w:
        assert w.getframerate() == stt.sample_rate and w.getnchannels() == 1
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = pcm.astype(np.float32) / 32768.0
    t = time.perf_counter()
    text = stt.transcribe(audio)
    print(f"[{(time.perf_counter() - t) * 1000:.0f} ms] {text}")
