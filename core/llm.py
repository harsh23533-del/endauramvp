"""
Single place where AURA talks to an LLM, via OpenRouter
(OpenAI-compatible API). Keeping this isolated means Planner/Coder
agents don't each duplicate API setup, and you can swap models in
one spot (or via .env, without touching code).
"""

import os
from openai import OpenAI

# Default free model. OpenRouter's free-tier lineup changes over time --
# if this one stops working, either:
#   1) set OPENROUTER_MODEL in your .env to a different ":free" model
#      from https://openrouter.ai/models?max_price=0, or
#   2) change the default below.
DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

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


def call_claude(system: str, user_message: str, max_tokens: int = 4000) -> str:
    client = _get_client()
    model = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError(
            f"OpenRouter returned an empty response (model: {model}). "
            "It may be rate-limited or unavailable -- try again in a "
            "minute, or set OPENROUTER_MODEL in .env to a different "
            "free model from https://openrouter.ai/models?max_price=0"
        )
    return content