"""User configuration, stored at ~/Library/Application Support/wispr-local/config.json (override with WISPR_CONFIG_DIR)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields

CONFIG_DIR = os.environ.get("WISPR_CONFIG_DIR", os.path.expanduser("~/Library/Application Support/wispr-local"))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


@dataclass
class Config:
    # pynput key name to hold while talking: ctrl (Control), ctrl_r, alt_r, cmd_r, f13, ...
    hotkey: str = "ctrl"
    # macOS virtual keycode used by the native app (59 = left Control). The key recorder in
    # Settings writes this; `hotkey` above is only used by the Python front end.
    hotkey_keycode: int = 59
    hotkey_label: str = "Control"
    # A quick tap (shorter than this, in seconds) toggles hands-free mode.
    tap_seconds: float = 0.25
    # Run a throwaway inference when the key goes down so the GPU is at full clock by the
    # time you release it (Whisper was ~0.5 s slower after a few seconds of idle).
    warm_on_start: bool = True

    # Whisper turbo fp16 (1.7 GB) was the most accurate on real recordings, ahead of the full
    # large-v3 and Parakeet. "-8bit" (0.9 GB) and "-4bit" (0.6 GB) gave near-identical text;
    # "mlx-community/parakeet-tdt-0.6b-v3" (8-bit at load, 0.8 GB) is fastest but mishears jargon.
    stt_model: str = "mlx-community/whisper-large-v3-turbo"
    # Spoken language for Whisper ("en", "zh", ...). None = auto-detect per 30 s window, which
    # is what produced Korean/Chinese garbage on silent windows.
    language: str | None = "en"
    # Quantize Parakeet's linear layers at load: 8 = same transcripts as bf16 at ~60% memory.
    stt_quant_bits: int | None = 8
    # Transcribe finished phrases in the background while you are still talking, so the wait
    # after release is only the last phrase, however long the dictation.
    segment_while_recording: bool = True

    # Which model runs the LLM pass: "local" (mlx-lm), "claude" (Anthropic API), or "none".
    # Default is none: with Whisper the transcript is already clean, and the local 3B model
    # gets self-corrections wrong about half the time (a wrong correction flips meaning).
    # Set "claude" plus an ANTHROPIC_API_KEY for reliable corrections.
    formatter: str = "none"
    llm_model: str = "mlx-community/Qwen2.5-3B-Instruct-4bit"
    claude_model: str = "claude-opus-5"
    # "always": LLM on every dictation. "triggers": only when the transcript contains a
    # self-correction or formatting phrase ("no wait", "actually", "new line", ...);
    # everything else gets the ~0 ms rule-based cleanup. "never": rules only.
    llm_mode: str = "triggers"
    # Extra trigger phrases on top of the built-in list (wispr.formatter.DEFAULT_TRIGGERS).
    extra_triggers: list[str] = field(default_factory=list)
    # Utterances with fewer words than this skip the LLM (rule-based cleanup only).
    min_words_for_llm: int = 4
    max_output_tokens: int = 400

    # "clipboard" (set clipboard + Cmd+V, then restore clipboard) or "type"
    # (synthesize keystrokes; slower for long text but leaves the clipboard alone)
    paste_mode: str = "clipboard"

    sample_rate: int = 16000
    max_seconds: int = 180
    log_dir: str = os.path.join(CONFIG_DIR, "logs")
    # Extra vocabulary the formatter should spell correctly (names, products, jargon).
    vocabulary: list[str] = field(default_factory=list)
    # Personal dictionary: exact phrase -> replacement, applied to every dictation
    # (case-insensitive, whole words). The cheapest fix for recurring mishearings.
    replacements: dict[str, str] = field(default_factory=lambda: {
        "a LLM": "an LLM",
        "to L and pass": "an LLM pass",
        "L and pass": "LLM pass",
        "text of speech": "text to speech",
        "Texas speech": "text to speech",
        "Dennis Hassabis": "Demis Hassabis",
    })
    # Save each recording as a wav next to the history log (for building an STT eval
    # from your own voice). ~2 MB per minute of speech.
    save_audio: bool = True

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            known = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in known:
                    setattr(cfg, k, v)
        return cfg

    def save(self) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(asdict(self), f, indent=2)
