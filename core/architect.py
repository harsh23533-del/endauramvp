"""
Architect agent.
Decides the technical approach before planning begins.
"""
import json
from core.llm import call_claude

ARCHITECT_SYSTEM_PROMPT = """You are the Architect agent inside AURA, an autonomous \
software engineering system.

Given a user's request, decide the minimal technical approach: language, framework, \
whether a database is needed, and any key libraries.

Rules:
- Keep it minimal -- this is an MVP, not a full product.
- Only include a database if the request clearly needs persistent structured data.
- Respond ONLY with valid JSON, no markdown fences, no preamble.
- Format:
{
  "stack": {"language": "python", "framework": "flask"},
  "needs_database": false,
  "notes": "one or two sentences justifying the choice"
}
"""


def design(user_request: str) -> dict:
    response_text = call_claude(
        system=ARCHITECT_SYSTEM_PROMPT,
        user_message=user_request,
        max_tokens=800,
    )
    cleaned = response_text.strip().strip("```").strip()
    if cleaned.startswith("json"):
        cleaned = cleaned[4:].strip()
    return json.loads(cleaned)