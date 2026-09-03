"""
Single place where AURA talks to an LLM, via OpenRouter
(OpenAI-compatible API). Keeping this isolated means agents don't
each duplicate API setup, retry logic, or JSON-parsing.

Includes a model fallback chain: OpenRouter's free-tier daily limit
(50 requests) is per-model, so when one model is rate-limited or
temporarily unavailable, this automatically tries the next model in
the chain instead of retrying the same exhausted model.

PDF section 39 addition -- model router:
Callers can now pass role="reasoning" | "coding" | "fast" instead of
(or alongside) a hard-coded model. Each role resolves to its own
primary model (overridable per-role via env vars), still falling back
through FALLBACK_CANDIDATES on rate-limit/unavailability exactly as
before. Passing no role (the default) keeps the old single-chain
behavior unchanged -- this is additive, not a breaking change.
"""

import contextvars
import json
import os
import re
import time
from openai import OpenAI
from core import metrics

# Per-build API key override (PDF section: bring-your-own-key).
#
# server.py runs exactly one build at a time on a single background
# worker thread (see its module docstring), so a contextvar set for the
# duration of that build is enough to route every LLM call made deep
# inside the agent pipeline -- architect, coder, debugger, etc. -- to a
# caller-supplied OpenRouter key instead of the server's own, without
# threading an api_key parameter through 30+ agent modules.
_request_api_key: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "aura_request_api_key", default=None
)


class use_api_key:
    """
    Context manager: run the wrapped block using `api_key` for every
    LLM call made inside it, instead of the server's own
    OPENROUTER_API_KEY. Pass None (or a blank string) to fall back to
    the server's key -- callers don't need to branch on whether the
    user supplied one.

        with use_api_key(user_supplied_key):
            build(user_request)
    """

    def __init__(self, api_key: str | None):
        self.api_key = api_key.strip() if api_key else None
        self._token = None

    def __enter__(self):
        self._token = _request_api_key.set(self.api_key)
        return self

    def __exit__(self, exc_type, exc, tb):
        _request_api_key.reset(self._token)
        return False

# Default free model. OpenRouter's free-tier lineup changes over time --
# if this one stops working, either:
#   1) set OPENROUTER_MODEL in your .env to a different ":free" model
#      from https://openrouter.ai/models?max_price=0, or
#   2) change the default below.
# Verified live against https://openrouter.ai/api/v1/models on 2026-08-26 --
# every model previously hardcoded here had been removed from the free
# catalog entirely (confirmed via a live fetch, not guessed).
DEFAULT_MODEL = "thinkingmachines/inkling:free"

# Verified-live free models (confirmed working via OpenRouter's live
# model list, 2026-08-26) used as automatic fallbacks when the primary
# model hits its daily rate limit or is temporarily unavailable.
FALLBACK_CANDIDATES = [
    "poolside/laguna-s-2.1:free",
    "thinkingmachines/inkling-small:free",
    "nvidia/nemotron-3.5-lightning:free",
    "poolside/laguna-xs-2.1:free",
    "liquid/lfm-2.5-2.6b:free",
]

# Model router (section 39): which env var and default each role
# resolves to. Picks matched to what each free model is actually good at
# (per OpenRouter's own listing) rather than reusing one model for
# everything: laguna-s-2.1 is purpose-built as a coding-agent model,
# nemotron-3.5-lightning is a small, fast model meant for high-throughput
# lightweight work.
ROLE_DEFAULTS = {
    "reasoning": ("OPENROUTER_MODEL_REASONING", DEFAULT_MODEL),           # architecture, debugging, planning
    "coding":    ("OPENROUTER_MODEL_CODING", "poolside/laguna-s-2.1:free"),  # code generation, refactoring
    "fast":      ("OPENROUTER_MODEL_FAST", "nvidia/nemotron-3.5-lightning:free"),  # classification, routing, extraction
}

_client = None


def _get_client() -> OpenAI:
    # A per-build caller-supplied key (see use_api_key above) always wins
    # and never touches the cached server-key client below -- built fresh
    # each time since it's scoped to one build, not the process lifetime.
    override_key = _request_api_key.get()
    if override_key:
        return OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=override_key,
            timeout=30.0,
            max_retries=0,
        )

    global _client
    if _client is None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Add it to your .env file, "
                "or supply your own key with use_api_key()/--api-key/the "
                "web form's \"Your own API key\" field."
            )
        _client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            timeout=30.0,
            max_retries=0,
        )
    return _client


def _model_chain(role: str = None) -> list:
    """
    Primary model first, then fallbacks.

    Resolution order for the primary model:
      1. OPENROUTER_MODEL env var (explicit global override -- always wins)
      2. the role's own env var / default, if a role was given
      3. DEFAULT_MODEL
    """
    explicit_override = os.environ.get("OPENROUTER_MODEL")
    if explicit_override:
        primary = explicit_override
    elif role and role in ROLE_DEFAULTS:
        env_var, role_default = ROLE_DEFAULTS[role]
        primary = os.environ.get(env_var, role_default)
    else:
        primary = DEFAULT_MODEL
    return [primary] + [m for m in FALLBACK_CANDIDATES if m != primary]


def _is_rate_limit_or_unavailable(error_text: str) -> bool:
    lowered = error_text.lower()
    return "429" in error_text or "rate limit" in lowered or "404" in error_text or "unavailable" in lowered


def _is_daily_quota_error(error_text: str) -> bool:
    """
    OpenRouter's free-tier daily cap (50/day with no credits purchased,
    1000/day once you've bought $10+ lifetime) is ACCOUNT-WIDE across
    every :free model -- not per-model. So a 429 that mentions "day" or
    "daily" means every model in FALLBACK_CANDIDATES will also fail;
    hopping to the next model just burns time and (per OpenRouter's own
    docs) failed attempts still count against the same quota.
    """
    lowered = error_text.lower()
    return "429" in error_text and ("day" in lowered or "daily" in lowered)


def call_claude(system: str, user_message: str, max_tokens: int = 4000, retries: int = 2, role: str = None) -> str:
    """
    Call the LLM, retrying transient errors on the same model, and
    automatically moving to the next model in the fallback chain if
    the current one is rate-limited or unavailable -- retrying an
    exhausted daily quota just wastes time.

    Two things bound the worst case, both important on a shared/hosted
    deployment where the account-wide free-tier quota (50/day) can be
    exhausted by other users' builds:
      - a wall-clock budget (AURA_LLM_CALL_BUDGET_SECONDS, default 60s)
        across the WHOLE call -- every model x every retry combined --
        so one call can never block for the theoretical worst case of
        ~6 models x 3 attempts x 30s timeout (~9-10 minutes). Without
        this, a build can look "stuck" on whichever stage happens to be
        mid-call when the quota runs out, because nothing else in the
        pipeline reports progress until that single call finally gives
        up or succeeds.
      - a print() per attempt, so the build's log (visible via the web
        UI's log panel / log_tail) shows which model is being tried and
        why it failed in real time, instead of going silent for the
        entire duration of a slow/exhausted call.

    role: optional model-router hint ("reasoning" | "coding" | "fast").
    """
    client = _get_client()
    last_error = None
    call_id = metrics.new_call_id()
    call_start = time.time()
    budget = float(os.environ.get("AURA_LLM_CALL_BUDGET_SECONDS", "60"))
    tried = []

    for model in _model_chain(role):
        for attempt in range(retries + 1):
            elapsed = time.time() - call_start
            if elapsed > budget:
                raise RuntimeError(
                    f"LLM call exceeded its {budget:.0f}s time budget after "
                    f"{elapsed:.0f}s (tried: {', '.join(tried) or 'nothing yet'}). "
                    f"This stops a single call from blocking the whole build for "
                    f"minutes when the free-tier quota is exhausted -- retry the "
                    f"build, add your own OpenRouter key, or raise "
                    f"AURA_LLM_CALL_BUDGET_SECONDS. Last error: {last_error}"
                )
            print(f"    [llm] {model} (attempt {attempt + 1}/{retries + 1})...")
            start = time.time()
            try:
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_message},
                    ],
                    # Root cause of a whole class of bad output (a file's
                    # content becomes literally "Here's a thinking
                    # process: 1. Analyze User Request..." with no code
                    # at all; a reviewer JSON parse failing on a stray
                    # `{`/`}` from CSS mentioned mid-reasoning): several
                    # of the free-tier models in this chain are
                    # reasoning models that, by default, put their
                    # chain-of-thought straight into `message.content`
                    # instead of a separate channel -- and can burn the
                    # entire max_tokens budget "thinking" before ever
                    # emitting the actual file/JSON. OpenRouter's unified
                    # `reasoning` request param (supported by every
                    # model, extra_body since it's not part of the
                    # OpenAI SDK's typed surface) tells the model to
                    # keep reasoning internally but strip it from the
                    # response entirely. See
                    # https://openrouter.ai/docs/use-cases/reasoning-tokens
                    extra_body={"reasoning": {"exclude": True}},
                )
                latency = time.time() - start
                content = response.choices[0].message.content
                usage = getattr(response, "usage", None)
                prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
                completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
                if content and content.strip():
                    metrics.record_attempt(call_id, model, attempt, latency, True,
                                            prompt_tokens, completion_tokens)
                    return content
                metrics.record_attempt(call_id, model, attempt, latency, False,
                                        prompt_tokens, completion_tokens, error="empty response")
                last_error = f"empty response (model: {model})"
                print(f"    [llm] {model} returned an empty response, retrying...")
                tried.append(f"{model} (empty)")
            except Exception as e:
                latency = time.time() - start
                metrics.record_attempt(call_id, model, attempt, latency, False, error=str(e))
                last_error = f"{model}: {e}"
                tried.append(model)
                print(f"    [llm] {model} failed: {str(e)[:150]}")
                if _is_daily_quota_error(str(e)):
                    # Account-wide daily cap hit -- every remaining model
                    # in the chain shares this same quota, so stop
                    # immediately instead of burning the rest of the chain.
                    raise RuntimeError(
                        f"OpenRouter daily free-tier quota exhausted (account-wide, "
                        f"not per-model): {e}\n"
                        f"Buy $10+ of OpenRouter credit (one-time, never has to be "
                        f"spent) to raise the cap from 50/day to 1000/day, or wait "
                        f"until the daily reset."
                    ) from e
                if _is_rate_limit_or_unavailable(str(e)):
                    break  # don't waste retries on an exhausted/unavailable model
            if attempt < retries:
                time.sleep(2 * (attempt + 1))  # 2s, then 4s backoff

    raise RuntimeError(
        f"LLM call failed on every model in the fallback chain. Last error: {last_error}\n"
        f"Tried: {', '.join(_model_chain(role))}\n"
        f"Set OPENROUTER_MODEL in .env to force a specific model, or check "
        f"https://openrouter.ai/models?max_price=0 for currently-live free models."
    )


def _iter_balanced_json_candidates(text: str):
    """
    Yield every syntactically-balanced, string-quote-aware {...}
    substring in text, trying EVERY '{' as a possible start (not just
    resuming after the previous match) -- a stray, never-actually-closed
    '{' earlier in the text (e.g. unrelated prose) would otherwise
    swallow everything after it into one bogus giant span, since brace-
    depth counting alone can't tell "prose brace" from "JSON brace".
    _extract_json below picks the longest candidate that actually
    parses, which in practice is the real (outermost, complete) object
    rather than a coincidental nested fragment or a bogus prose span.
    """
    n = len(text)
    for start in range(n):
        if text[start] != "{":
            continue
        depth = 0
        in_string = False
        escape = False
        for j in range(start, n):
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[start:j + 1]
                    break


def _extract_json(text: str) -> str:
    """
    Best-effort cleanup of an LLM response before json.loads: strip
    markdown fences, then -- if there's stray prose around (or between)
    JSON-looking braces -- find every balanced {...} candidate and
    return the LONGEST one that actually parses as JSON (the real,
    complete answer is virtually always the biggest valid object; a
    shorter one that also happens to parse is more likely an incidental
    nested fragment or unrelated prose brace). Falls back to a naive
    first-'{'-to-last-'}' slice only if nothing balanced parses at all.
    """
    text = text.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    if text.startswith("json"):
        text = text[4:].strip()

    candidates = list(_iter_balanced_json_candidates(text))
    parseable = []
    for candidate in candidates:
        try:
            json.loads(candidate)
            parseable.append(candidate)
        except json.JSONDecodeError:
            continue
    if parseable:
        return max(parseable, key=len)
    if candidates:
        return max(candidates, key=len)  # best guess; caller's retry-on-failure loop still applies

    # Nothing balanced found at all (e.g. truncated mid-object) -- last-
    # resort naive slice, better than returning the raw prose untouched.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    return text


def call_claude_json(system: str, user_message: str, max_tokens: int = 4000, retries: int = 2, role: str = None) -> dict:
    """
    Call the LLM and parse its response as JSON, retrying the whole
    call (not just the parse) if the model returns malformed JSON --
    a fresh generation is more likely to fix it than re-parsing the
    same broken text.

    role: optional model-router hint ("reasoning" | "coding" | "fast").
    """
    last_error = None
    for attempt in range(retries + 1):
        response_text = call_claude(system=system, user_message=user_message, max_tokens=max_tokens, role=role)
        cleaned = _extract_json(response_text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            last_error = f"{e} -- raw response started with: {response_text[:200]!r}"
            if attempt < retries:
                continue

    raise RuntimeError(
        f"LLM did not return valid JSON after {retries + 1} attempts. Last error: {last_error}"
    )
