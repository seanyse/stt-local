# wispr-local

Local, hold-to-talk dictation for macOS with an LLM cleanup pass. A self-hosted take on Wispr Flow:
hold a key, talk, release, and clean text lands in whatever app has focus. Nothing leaves the machine
unless you opt into the Claude backend.

## How it works

```
hold key ──► mic buffer ──► Whisper large-v3-turbo (MLX) ──► dictionary + rules (LLM optional) ──► Cmd+V into focused app
                            speech-to-text, ~0.9 s flat         ~0 ms  /  ~300-900 ms
```

1. **Audio** – the mic stream is always open (`wispr/audio.py`), so pressing the key costs nothing; samples are only buffered while the key is held.
2. **Speech-to-text** – Whisper large-v3-turbo via `mlx-whisper` (fp16, 1.7 GB; the 8-bit and 4-bit variants gave near-identical text at 0.9 / 0.6 GB), prompted with your `vocabulary`, language forced, cross-window conditioning and temperature fallback off, and repetitive segments dropped. Those last three matter: on a recording with a silent tail the stock settings hallucinated a 20x repeated phrase, retried at higher temperatures for 15 s, and drifted into Korean/Chinese tokens. Alternative: `mlx-community/parakeet-tdt-0.6b-v3`, quantized to 8-bit at load (0.8 GB), ~20 ms per second of audio, weaker on jargon.

   Accuracy comparison on 12 real recordings (184 s): turbo was the most accurate; the full `whisper-large-v3` was worse ("Texas beach", "She crashed a movie") at 2x the time, Parakeet was worst on jargon, and gain-normalizing the quiet mic signal changed nothing.

   **Transcribe while talking** (`segment_while_recording`): every 250 ms the engine looks at the audio so far and hands each finished phrase to the model in the background, so on release only the last phrase is left however long the dictation. A phrase ends only at a pause of ≥ 1 s that is followed by speech again, never before 8 s, and each phrase is decoded with the previous phrases as prompt context. Those rules matter: an earlier version cut at 0.6 s pauses and split "into a … two gigabyte territory" mid-sentence, which Whisper decoded as "a tube. Take a back territory". Measured with real recordings replayed in real time: 31 s clip → 3 ms wait; 78 s → 0.8 s.
3. **Formatting pass** – off by default (`formatter: "none"`): the personal dictionary (`replacements`) and a rule-based cleanup (fillers, doubled words) run on every dictation at no cost. With `formatter` set to `local` or `claude`, `llm_mode: "triggers"` means the model runs only when the transcript contains a self-correction or formatting phrase. The LLM runs only when the transcript contains a self-correction or formatting phrase such as "no wait", "actually", "scratch that", "I mean", "new line" – the cases where it earns its latency. It then applies the correction ("bacon, actually not bacon, pancakes" → "pancakes"), fixes misheard words from context, and handles line breaks. Set `llm_mode` to `always` or `never` to change that. The system prompt lives in a pre-computed KV cache so each request only pays for the transcript tokens, and outputs that look like the model *answered* the dictation are rejected in favour of the rule-based cleanup.

   Local model choice, measured on an 11-case eval built from real dictations: Qwen2.5-3B-Instruct 4-bit scores 9/11 at ~500 ms, Qwen2.5-1.5B 8/11 at ~400 ms. The two misses need world knowledge ("Texas speech" → "text to speech"); for those, switch `formatter` to `claude`.
4. **Injection** – text goes on the clipboard and Cmd+V is synthesized; the previous clipboard is restored after 0.6 s. `paste_mode: "type"` synthesizes keystrokes instead.

## The macOS app

`macos/` is a native SwiftUI menu-bar app that drives the Python engine (`wispr.server`) as a subprocess over JSON lines:

- Hold-to-talk hotkey with a key recorder in Settings (modifier keys or any key; tap to lock hands-free; other keys pressed while holding cancel, so shortcuts keep working)
- Wispr-style floating "Listening / Transcribing" pill at the bottom of the screen
- History window: every dictation with timestamp and timing, copy button, play the saved recording, reveal the wav, show the raw transcript, search
- Settings: speech model, vocabulary, LLM pass and mode, personal dictionary, paste mode, audio saving, engine log and restart

```bash
macos/build.sh --install            # builds and copies to /Applications/Wispr Local.app
open -a "Wispr Local"
```

The bundle points at this repo's `.venv` and source (paths baked into its Info.plist), so keep the folder where it is or rebuild after moving it. On first launch grant **Accessibility** (hotkey + paste) and **Microphone** to "Wispr Local". The app is ad-hoc signed, so macOS may ask for Accessibility again after a rebuild. Quit the Python `./run.sh` front end before using the app, or both will react to the hotkey.

## Setup (engine only)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh            # Python-only menu-bar front end; models download on first run
./run.sh --headless # same thing, but logs to the terminal
```

macOS permissions (System Settings → Privacy & Security), granted to the app you launch from (Terminal, iTerm, …):

- **Microphone**
- **Accessibility** and **Input Monitoring** – for the global hotkey and the synthesized Cmd+V

Usage: hold **Control** (⌃) and talk, release to insert. A quick tap locks hands-free recording until the next tap.
The menu-bar icon shows 🎙 idle, 🔴 recording, ⏳ processing.

## Configuration

`~/Library/Application Support/wispr-local/config.json` is created on first run:

| key | default | notes |
|---|---|---|
| `hotkey` | `ctrl` | Python front end only; any pynput key name |
| `hotkey_keycode` / `hotkey_label` | `59` / `Control` | macOS app; set from the key recorder in Settings |
| `warm_on_start` | `true` | throwaway inference on key-down so Whisper runs at full GPU clock on release |
| `formatter` | `none` | which model runs the LLM pass: `none`, `local`, or `claude`. The local 3B model gets self-corrections wrong about half the time; `claude` is the reliable option |
| `llm_mode` | `triggers` | `triggers`, `always`, or `never` |
| `extra_triggers` | `[]` | extra phrases that force the LLM pass |
| `llm_model` | `mlx-community/Qwen2.5-3B-Instruct-4bit` | `Qwen2.5-1.5B-Instruct-4bit` is a bit faster and slightly worse |
| `claude_model` | `claude-opus-5` | used when `formatter` is `claude`; export `ANTHROPIC_API_KEY` first. Runs at low effort with server-side refusal fallback. |
| `vocabulary` | `[]` | names and jargon, e.g. `["Wispr Flow", "Parakeet", "MLX"]`; given to the LLM, and to Whisper as its prompt |
| `replacements` | a few seeds | personal dictionary, exact phrase → replacement, applied to every dictation before anything else |
| `stt_model` | `mlx-community/whisper-large-v3-turbo` | `-8bit`, `-4bit`, or `mlx-community/parakeet-tdt-0.6b-v3` (8-bit at load, fastest, worse on jargon) |
| `language` | `en` | Whisper language; blank = auto-detect per window (caused Korean/Chinese garbage on silence) |
| `segment_while_recording` | `true` | transcribe finished phrases in the background while talking |
| `save_audio` | `true` | keep a wav of every dictation in the logs folder, for tuning speech-to-text on your own voice |
| `min_words_for_llm` | `4` | shorter utterances skip the LLM |
| `paste_mode` | `clipboard` | `clipboard` (paste + restore), `type`, `copy` (clipboard only), `none` |

Every dictation is appended to `~/Library/Application Support/wispr-local/logs/history.jsonl` with raw text, cleaned text and timings.

## Benchmark

```bash
.venv/bin/python bench.py                       # default model
.venv/bin/python bench.py mlx-community/Qwen2.5-0.5B-Instruct-4bit
```

Measured on an M1 Pro (16 GB):

| stage | 3 s utterance | 10 s utterance |
|---|---|---|
| speech-to-text, Whisper turbo 4-bit, one shot | ~0.8 s | ~0.9 s |
| speech-to-text, Parakeet v3 8-bit, one shot | ~140 ms | ~290 ms |
| wait after release with transcribe-while-talking, any length | last phrase only: ~0.8 s Whisper / ~0.2 s Parakeet | same |
| rule-based cleanup (no trigger) | ~0 ms | ~0 ms |
| LLM pass when triggered (Qwen2.5 3B 4-bit) | ~300-500 ms | ~600-900 ms |

## Resource cost of keeping the engine resident

Measured on the M1 Pro with Whisper turbo loaded, idle between dictations:

| | memory (phys footprint) | CPU idle |
|---|---|---|
| engine, Whisper turbo fp16 (default, most accurate) | ~1.7 GB | < 1% |
| engine, Whisper turbo 8-bit | ~0.9 GB | < 1% |
| engine, Whisper turbo 4-bit | ~0.65 GB | < 1% |
| engine, Parakeet v3 8-bit | ~0.8 GB | < 1% |
| Swift app | ~55 MB | ~0% (was 5% while a hidden overlay kept animating) |

CPU is a non-issue; memory is the cost. On a 16 GB machine under pressure the idle engine gets compressed or paged out, and the next dictation pays to bring it back: Whisper measured 0.72 s back-to-back, 1.3 s after 15 s idle, 2.3 s cold. `warm_on_start` fires a throwaway inference on key-down to absorb that while you speak; Parakeet is the option if the ~1 s matters more than jargon accuracy. Engine output is also written to `logs/engine.log`.

## Fixing mishearings

Small local LLMs do not reliably repair misheard words ("L and pass" for "LLM pass"), even with a vocabulary hint; measured, Qwen2.5-3B made such sentences worse as often as better. What works, in order of cost:

1. `replacements` – instant, deterministic. Add an entry whenever you see the same mistake twice.
2. `stt_model: whisper-large-v3-turbo` – its prompt biasing gets names like "Qwen" and "fetchUser" right at ~5x the STT latency.
3. `formatter: claude` – fixes them from context, with a network round trip.

The wavs in the logs folder are there so the choice can be measured on your own voice instead of guessed.

## Ideas for later

- Prompt-lookup speculative decoding for the formatter: the output is mostly a copy of the input, so drafting from the transcript n-grams could cut formatting time 2-3x.
- Streaming STT during recording (tested: `parakeet-mlx` streaming mode is currently slower per chunk than one batch pass, so it is off).
- Context awareness: pass the focused app name / selected text so the formatter can match tone (Slack vs. email vs. code comment).
- Snippets ("insert my address") and per-app tone.
- Fine-tune the 0.5B model on your own `history.jsonl` corrections for a faster, personalized pass.
