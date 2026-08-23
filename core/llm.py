"""
Single place where AURA talks to an LLM, via OpenRouter
(OpenAI-compatible API). Keeping this isolated means agents don't
each duplicate API setup, retry logic, or JSON-parsing.

Includes a model fallback chain: OpenRouter's free-tier daily limit
(50 requests) is per-model, so when one model is rate-limited or
temporarily unavailable, this automatically tries the next model in
the chain instead of retrying the same exhausted model.
"""

import json
import os
import re
import time
from openai import OpenAI

# Default free model. OpenRouter's free-tier lineup changes over time --
# if this one stops working, either:
#   1) set OPENROUTER_MODEL in your .env to a different ":free" model
#      from https://openrouter.ai/models?max_price=0, or
#   2) change the default below.
DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

# Verified-live free models (confirmed working via OpenRouter's live
# model list) used as automatic fallbacks when the primary model hits
# its daily rate limit or is temporarily unavailable.
FALLBACK_CANDIDATES = [
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "z-ai/glm-5.2:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-nano-9b-v2:free",
]

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
        )
    return _client


def _model_chain() -> list:
    """Primary model first (from .env or default), then fallbacks."""
    primary = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    return [primary] + [m for m in FALLBACK_CANDIDATES if m != primary]


def _is_rate_limit_or_unavailable(error_text: str) -> bool:
    lowered = error_text.lower()
    return "429" in error_text or "rate limit" in lowered or "404" in error_text or "unavailable" in lowered


def call_claude(system: str, user_message: str, max_tokens: int = 4000, retries: int = 2) -> str:
    """
    Call the LLM, retrying transient errors on the same model, and
    automatically moving to the next model in the fallback chain if
    the current one is rate-limited or unavailable -- retrying an
    exhausted daily quota just wastes time.
    """
    client = _get_client()
    last_error = None

    for model in _model_chain():
        for attempt in range(retries + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_message},
                    ],
                )
                content = response.choices[0].message.content
                if content and content.strip():
                    return content
                last_error = f"empty response (model: {model})"
            except Exception as e:
                last_error = f"{model}: {e}"
                if _is_rate_limit_or_unavailable(str(e)):
                    break  # don't waste retries on an exhausted/unavailable model
            if attempt < retries:
                time.sleep(2 * (attempt + 1))  # 2s, then 4s backoff

    raise RuntimeError(
        f"LLM call failed on every model in the fallback chain. Last error: {last_error}\n"
        f"Tried: {', '.join(_model_chain())}\n"
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


def call_claude_json(system: str, user_message: str, max_tokens: int = 4000, retries: int = 2) -> dict:
    """
    Call the LLM and parse its response as JSON, retrying the whole
    call (not just the parse) if the model returns malformed JSON --
    a fresh generation is more likely to fix it than re-parsing the
    same broken text.
    """
    last_error = None
    for attempt in range(retries + 1):
        response_text = call_claude(system=system, user_message=user_message, max_tokens=max_tokens)
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
