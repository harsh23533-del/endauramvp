"""
Architect agent.
Decides the technical approach before planning begins.
"""
from core.llm import call_claude_json

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
    return call_claude_json(
        system=ARCHITECT_SYSTEM_PROMPT,
        user_message=user_request,
        max_tokens=800,
    )
