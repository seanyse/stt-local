"""Latency benchmark: synthesize speech with macOS `say`, then time STT + formatting."""
from __future__ import annotations

import subprocess
import sys
import time
import wave

import numpy as np

from wispr.config import Config
from wispr.formatter import LocalFormatter, RuleFormatter, format_transcript
from wispr.stt import SpeechToText

SENTENCES = [
    "um so i was thinking we could uh push the launch to like next week what do you think",
    "hey can you send me the the report by tuesday no wait by wednesday thanks",
    "what's the capital of france",
    "okay so the main issue with the current design is that the cache gets invalidated every time we change the system prompt which means we pay the full prefill cost on every single request and that adds up really fast",
    "reminder to myself new line buy milk new line call mom about the weekend new paragraph that's it",
]


def synth(text: str, path: str) -> np.ndarray:
    subprocess.run(["say", "-o", path, "--data-format=LEI16@16000", text], check=True)
    with wave.open(path) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def main():
    cfg = Config.load()
    llm = sys.argv[1] if len(sys.argv) > 1 else cfg.llm_model
    print(f"STT: {cfg.stt_model}\nLLM: {llm}\n")
    stt = SpeechToText(cfg.stt_model)
    fmt = LocalFormatter(llm, cfg.max_output_tokens) if llm != "none" else RuleFormatter()

    for i, s in enumerate(SENTENCES):
        audio = synth(s, f"/tmp/wispr_bench_{i}.wav")
        secs = len(audio) / 16000
        t = time.perf_counter()
        raw = stt.transcribe(audio)
        t_stt = time.perf_counter() - t
        clean, t_fmt = format_transcript(fmt, raw, cfg.min_words_for_llm, cfg.llm_mode)
        print(f"--- {secs:.1f}s audio | stt {t_stt*1000:.0f}ms | format {t_fmt*1000:.0f}ms | total {(t_stt+t_fmt)*1000:.0f}ms")
        print(f"raw:   {raw}\nclean: {clean}\n")

    # Formatter-only timing on the raw sentences (skips the TTS/STT variance).
    print("=== formatter only, typed input ===")
    for s in SENTENCES:
        clean, t_fmt = format_transcript(fmt, s, cfg.min_words_for_llm, cfg.llm_mode)
        print(f"[{t_fmt*1000:.0f}ms] {clean!r}")


if __name__ == "__main__":
    main()
