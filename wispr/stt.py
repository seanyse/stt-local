"""Speech-to-text on Apple Silicon via MLX.

Engines, chosen by the model id:
  - Whisper (id contains "whisper"): mlx-whisper. Prompted with `vocabulary`, language forced,
    no cross-window conditioning and no temperature fallback (both caused minute-long
    hallucination loops on silent tails), repeated-text segments dropped.
  - Parakeet TDT (anything else): parakeet-mlx, ~20 ms per second of audio. Linear layers can
    be quantized at load (`quant_bits`); 8-bit gave identical transcripts to bf16 at ~60% memory.
"""
from __future__ import annotations

import os
import re
import time

import mlx.core as mx
import numpy as np

# Whisper emits these on silence or noise; drop them when the clip is short.
HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching", "you", "bye", "so", "the end", "subtitles by the amara.org community"}


def _link_weights(model_id: str) -> None:
    """Newer mlx-community Whisper repos ship model.safetensors; mlx-whisper looks for weights.safetensors."""
    try:
        from huggingface_hub import snapshot_download

        d = snapshot_download(model_id)
        want, have = os.path.join(d, "weights.safetensors"), os.path.join(d, "model.safetensors")
        if not os.path.exists(want) and os.path.exists(have):
            os.symlink("model.safetensors", want)
    except Exception:
        pass


class SpeechToText:
    def __init__(self, model_id: str = "mlx-community/whisper-large-v3-turbo-4bit", vocabulary: list[str] | None = None,
                 language: str | None = "en", quant_bits: int | None = 8):
        self.model_id = model_id
        self.sample_rate = 16000
        self.language = language or None
        self.prompt = ", ".join(vocabulary) + "." if vocabulary else None
        if "whisper" in model_id.lower():
            import mlx_whisper  # noqa: F401

            _link_weights(model_id)
            self.engine = "whisper"
            self.model = None
        else:
            import mlx.nn as nn
            from parakeet_mlx import from_pretrained

            self.engine = "parakeet"
            self.model = from_pretrained(model_id)
            if quant_bits:
                nn.quantize(self.model, group_size=64, bits=quant_bits,
                            class_predicate=lambda p, m: isinstance(m, nn.Linear) and m.weight.shape[-1] % 64 == 0)
            self.sample_rate = self.model.preprocessor_config.sample_rate
        self.warmup()

    def warmup(self) -> None:
        self.transcribe(np.zeros(self.sample_rate, dtype=np.float32))

    def transcribe(self, audio: np.ndarray) -> str:
        """audio: float32 mono at self.sample_rate."""
        if audio.size < self.sample_rate // 10:
            return ""
        try:
            return self._transcribe(audio)
        finally:
            # MLX keeps freed buffers cached; give them back so the idle engine is mostly weights.
            mx.clear_cache()

    def _transcribe(self, audio: np.ndarray) -> str:
        if self.engine == "whisper":
            import mlx_whisper

            out = mlx_whisper.transcribe(
                audio.astype(np.float32), path_or_hf_repo=self.model_id, initial_prompt=self.prompt,
                language=self.language, condition_on_previous_text=False, temperature=0.0, fp16=True,
            )
            parts = []
            for seg in out["segments"]:
                t = seg["text"].strip()
                if not t or seg.get("no_speech_prob", 0) > 0.8 and seg.get("avg_logprob", 0) < -1.0:
                    continue
                if seg.get("compression_ratio", 0) > 2.4 or _is_repetitive(t):
                    continue
                parts.append(t)
            text = " ".join(parts).strip()
            if len(audio) < self.sample_rate * 4 and text.lower().strip(".!,") in HALLUCINATIONS:
                return ""
            return text

        from parakeet_mlx.audio import get_logmel

        mel = get_logmel(mx.array(audio.astype(np.float32)), self.model.preprocessor_config)
        return self.model.generate(mel)[0].text.strip()


def _is_repetitive(text: str) -> bool:
    """'So, you can think of it. So, you can think of it. ...' style loops."""
    words = re.findall(r"\w+", text.lower())
    if len(words) < 12:
        return False
    for n in (3, 4, 5, 6):
        grams = [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]
        if grams and max(grams.count(g) for g in set(grams)) >= 4:
            return True
    return False


if __name__ == "__main__":
    import sys
    import wave

    stt = SpeechToText(sys.argv[2] if len(sys.argv) > 2 else "mlx-community/whisper-large-v3-turbo-4bit")
    with wave.open(sys.argv[1]) as w:
        assert w.getframerate() == stt.sample_rate and w.getnchannels() == 1
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = pcm.astype(np.float32) / 32768.0
    t = time.perf_counter()
    text = stt.transcribe(audio)
    print(f"[{(time.perf_counter() - t) * 1000:.0f} ms] {text}")
