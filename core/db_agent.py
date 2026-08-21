"""
Database agent.
Only invoked when the Architect flags the project as needing a database.
"""
from core.llm import call_claude

DB_SYSTEM_PROMPT = """You are the Database agent inside AURA, an autonomous \
software engineering system.

Given a project goal, design a minimal database schema for it (SQLite, unless \
the goal clearly requires something else).

Rules:
- Output ONLY the raw SQL schema content (CREATE TABLE statements). No markdown \
fences, no explanation.
- Keep it minimal -- only the tables actually needed.
"""


def design_schema(user_request: str) -> str:
    response_text = call_claude(
        system=DB_SYSTEM_PROMPT,
        user_message=f"Project goal: {user_request}\n\nWrite schema.sql now.",
        max_tokens=1500,
    )
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    return cleaned