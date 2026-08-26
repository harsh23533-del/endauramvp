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

import json
import os
import re
import time
from openai import OpenAI
from core import metrics

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
    global _client
    if _client is None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Add it to your .env file."
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


def call_claude(system: str, user_message: str, max_tokens: int = 4000, retries: int = 2, role: str = None) -> str:
    """
    Call the LLM, retrying transient errors on the same model, and
    automatically moving to the next model in the fallback chain if
    the current one is rate-limited or unavailable -- retrying an
    exhausted daily quota just wastes time.

    role: optional model-router hint ("reasoning" | "coding" | "fast").
    """
    client = _get_client()
    last_error = None
    call_id = metrics.new_call_id()

    for model in _model_chain(role):
        for attempt in range(retries + 1):
            start = time.time()
            try:
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_message},
                    ],
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
            except Exception as e:
                latency = time.time() - start
                metrics.record_attempt(call_id, model, attempt, latency, False, error=str(e))
                last_error = f"{model}: {e}"
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


def _extract_json(text: str) -> str:
    """
    Best-effort cleanup of an LLM response before json.loads:
    strip markdown fences, and if there's stray prose around the
    JSON object, cut down to the outermost {...} block.
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

    if not text.startswith("{"):
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
