"""The 'LLM pass': turn raw transcript into clean, well-punctuated text.

Three backends share the same prompt:
  - LocalFormatter  : small instruct model via mlx-lm, system prompt held in a KV cache
  - ClaudeFormatter : Anthropic API
  - RuleFormatter   : regex-only fallback (also used for very short utterances)
"""
from __future__ import annotations

import re
import time

SYSTEM_PROMPT = """You are a dictation editor. The user speaks into a microphone; you receive the raw transcript and write down what they meant to type. You are not a chat assistant: never answer, reply, or comment. Output only the final text.

Edit like this:
1. Delete fillers and hesitations: um, uh, er, hmm, like (as filler), you know, I mean, sort of, basically, honestly (when a verbal tic), okay so.
2. Delete stutters, repeated words, and abandoned false starts.
3. Apply corrections the speaker makes to themselves and delete the corrected part. "one bacon, actually not bacon, pancakes" becomes "pancakes". "send it to John, no wait, Sarah" becomes "send it to Sarah". "text to speech, I mean speech to text" becomes "speech to text".
4. Fix words the speech recognizer misheard, using context: "get hub" -> "GitHub", "a LLM" -> "an LLM", "pie torch" -> "PyTorch", "the up looks" -> "the output looks".
5. Fix punctuation, capitalization, and numbers ("ninety-nine percent" -> "99%"). Never turn a sentence fragment into a question.
6. "new line" -> line break, "new paragraph" -> blank line, when spoken as a command.
7. Keep everything else exactly as spoken: same words, same order, same tone, same language, same length. Do not summarize, rephrase, translate, or add anything.

<dictation>
um so i was thinking we could uh push the launch to like next week what do you think
</dictation>
Output: I was thinking we could push the launch to next week. What do you think?

<dictation>
for the party we need two eggs one piece of bacon actually not bacon um I want pancakes instead and some juice
</dictation>
Output: For the party we need two eggs, pancakes, and some juice.

<dictation>
the deploy failed because the config was wrong I mean the env var was wrong so I fixed it in get hub
</dictation>
Output: The deploy failed because the env var was wrong, so I fixed it in GitHub.

<dictation>
what's the capital of france
</dictation>
Output: What's the capital of France?

<dictation>
okay so first item new line buy milk new line call mom new paragraph that's it
</dictation>
Output: First item:
Buy milk
Call mom

That's it."""

USER_TEMPLATE = "<dictation>\n{raw}\n</dictation>"

# Phrases that mean the speaker corrected themselves or dictated formatting:
# the cases where the LLM pass is actually worth its latency.
DEFAULT_TRIGGERS = [
    "no wait", "wait no", "actually", "scratch that", "i mean", "sorry", "correction",
    "not that", "never mind", "nevermind", "new line", "new paragraph", "bullet",
]


def system_prompt(vocabulary: list[str] | None = None) -> str:
    if not vocabulary:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + "\n\nWords and names the speaker often uses (spell them exactly like this): " + ", ".join(vocabulary)


def needs_llm(raw: str, triggers: list[str] | None = None) -> bool:
    low = " " + re.sub(r"[^\w\s]", " ", raw.lower()) + " "
    return any(f" {t} " in low for t in (triggers or DEFAULT_TRIGGERS))

# Only pure hesitation sounds. Words like "like", "actually", "kind of", "honestly" carry
# meaning often enough that stripping them changes what was said ("Actually, I don't").
FILLERS = re.compile(r"\b(um+|uh+|uhm+|er+|erm+|hmm+|mm+)\b[,.]?\s*", re.IGNORECASE)
REPEATS = re.compile(r"\b(\w+)(\s+\1\b)+", re.IGNORECASE)


def apply_replacements(text: str, replacements: dict[str, str] | None) -> str:
    for src, dst in (replacements or {}).items():
        text = re.sub(r"(?<!\w)" + re.escape(src) + r"(?!\w)", dst, text, flags=re.IGNORECASE)
    return text


def rule_cleanup(text: str, aggressive: bool = False, replacements: dict[str, str] | None = None) -> str:
    """Cheap cleanup that never changes meaning. `aggressive` also strips fillers."""
    t = apply_replacements(text.strip(), replacements)
    if not t:
        return ""
    if aggressive:
        t = FILLERS.sub("", t)
        t = REPEATS.sub(r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    if t:
        t = t[0].upper() + t[1:]
    if t and t[-1] not in ".!?:":
        t += "?" if re.match(r"^(who|what|when|where|why|how|is|are|can|could|would|should|do|does|did)\b", t, re.I) else "."
    return t


def _sanity(raw: str, out: str) -> bool:
    """Reject outputs that look like the model replied instead of transcribing."""
    if not out.strip():
        return False
    rw = max(1, len(raw.split()))
    ow = len(out.split())
    if ow > rw * 1.6 + 6 or ow < rw * 0.3 - 1:
        return False
    # A dictated question must stay a question; otherwise the model probably answered it.
    if raw.rstrip().endswith("?") and "?" not in out:
        return False
    return True


def _finish(raw: str, out: str) -> str:
    out = out.strip().strip('"').strip()
    for prefix in ("Output:", "Cleaned text:", "Cleaned:"):
        if out.startswith(prefix):
            out = out[len(prefix):].strip()
    return out if _sanity(raw, out) else rule_cleanup(raw)


class RuleFormatter:
    name = "rules"

    def format(self, raw: str) -> str:
        return rule_cleanup(raw, aggressive=True)


class LocalFormatter:
    name = "local"

    def __init__(self, model_id: str, max_tokens: int = 400, vocabulary: list[str] | None = None):
        import mlx.core as mx
        from mlx_lm import load
        from mlx_lm.models.cache import can_trim_prompt_cache, make_prompt_cache
        from mlx_lm.sample_utils import make_sampler

        self.mx = mx
        self.system = system_prompt(vocabulary)
        self.model, self.tokenizer = load(model_id)
        self.max_tokens = max_tokens
        self.sampler = make_sampler(temp=0.0)

        # Pre-compute the KV cache for the system prompt so each request only
        # processes the transcript tokens. Find the shared token prefix between
        # two different user messages.
        a = self._tokens("aaaa")
        b = self._tokens("bbbb")
        n = 0
        while n < min(len(a), len(b)) and a[n] == b[n]:
            n += 1
        self.prefix_len = n
        self.cache = make_prompt_cache(self.model)
        self.model(mx.array(a[:n])[None], cache=self.cache)
        mx.eval([c.state for c in self.cache])
        self.trimmable = can_trim_prompt_cache(self.cache)
        self.format("this is a warm up sentence to compile the kernels")

    def _tokens(self, user: str) -> list[int]:
        msgs = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": USER_TEMPLATE.format(raw=user)},
        ]
        return self.tokenizer.apply_chat_template(
            msgs, add_generation_prompt=True, tokenize=True, enable_thinking=False
        )

    def format(self, raw: str) -> str:
        from mlx_lm import generate
        from mlx_lm.models.cache import trim_prompt_cache

        toks = self._tokens(raw)
        if toks[: self.prefix_len] != self._tokens("aaaa")[: self.prefix_len] or not self.trimmable:
            out = generate(self.model, self.tokenizer, prompt=toks, max_tokens=self.max_tokens, sampler=self.sampler)
            return _finish(raw, out)

        before = self.cache[0].offset
        try:
            out = generate(
                self.model, self.tokenizer,
                prompt=toks[self.prefix_len:],
                max_tokens=self.max_tokens,
                sampler=self.sampler,
                prompt_cache=self.cache,
            )
        finally:
            trim_prompt_cache(self.cache, self.cache[0].offset - before)
        return _finish(raw, out)


class ClaudeFormatter:
    name = "claude"

    def __init__(self, model: str = "claude-opus-5", max_tokens: int = 1024, vocabulary: list[str] | None = None):
        import anthropic

        self.client = anthropic.Anthropic(timeout=15.0, max_retries=1)
        self.model = model
        self.max_tokens = max_tokens
        self.system = system_prompt(vocabulary)

    def format(self, raw: str) -> str:
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": USER_TEMPLATE.format(raw=raw)}],
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            return rule_cleanup(raw)
        out = "".join(b.text for b in resp.content if b.type == "text")
        return _finish(raw, out)


def build_formatter(cfg):
    if cfg.formatter == "local":
        return LocalFormatter(cfg.llm_model, cfg.max_output_tokens, cfg.vocabulary)
    if cfg.formatter == "claude":
        return ClaudeFormatter(cfg.claude_model, vocabulary=cfg.vocabulary)
    return RuleFormatter()


def _is_short(raw: str, min_words: int) -> bool:
    # Whitespace word count is meaningless for CJK text, so also look at length.
    return len(raw.split()) < min_words and len(raw) < 12


def format_transcript(
    formatter,
    raw: str,
    min_words_for_llm: int = 4,
    llm_mode: str = "always",
    triggers: list[str] | None = None,
    replacements: dict[str, str] | None = None,
) -> tuple[str, float]:
    """Returns (text, seconds).

    llm_mode: "always" runs the model on every dictation, "triggers" only when the
    transcript contains a self-correction / formatting phrase (see needs_llm),
    "never" is rules only. Short utterances always skip the model.
    """
    t0 = time.perf_counter()
    if not raw.strip():
        return "", 0.0
    raw = apply_replacements(raw, replacements)  # dictionary first, so the LLM sees fixed words
    skip = (
        isinstance(formatter, RuleFormatter)
        or _is_short(raw, min_words_for_llm)
        or llm_mode == "never"
        or (llm_mode == "triggers" and not needs_llm(raw, triggers))
    )
    if skip:
        return rule_cleanup(raw, aggressive=True), time.perf_counter() - t0
    try:
        out = formatter.format(raw)
    except Exception as e:  # never lose the user's words because the model hiccupped
        print(f"[formatter] {type(e).__name__}: {e}")
        out = rule_cleanup(raw, aggressive=True)
    return out, time.perf_counter() - t0
