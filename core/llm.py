"""
Single place where AURA talks to the LLM.
Using OpenRouter's free-tier router (same pattern as processbot) so this
can be tested with zero cost.
"""
import os
import time
from openai import OpenAI

MODEL = "openrouter/free"
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Add it to your .env file. "
                "Get a free key at https://openrouter.ai/keys"
            )
        _client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
    return _client


def _clean_reply(text: str) -> str:
    return text.strip()


def call_claude(system: str, user_message: str, max_tokens: int = 4000, max_retries: int = 2) -> str:
    client = _get_client()
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
            )
            content = response.choices[0].message.content
            if content and content.strip():
                return _clean_reply(content)
            last_error = RuntimeError("Empty response from model")
        except Exception as e:
            last_error = e
        if attempt < max_retries:
            time.sleep(1.5)
    raise RuntimeError(f"OpenRouter call failed after {max_retries + 1} attempts: {last_error}")