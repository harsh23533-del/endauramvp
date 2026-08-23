"""
Reviewer agent.
Reviews the written files for quality issues. Does not write code.
"""
from core.llm import call_claude_json

REVIEWER_SYSTEM_PROMPT = """You are the Code Reviewer agent inside AURA, an autonomous \
software engineering system.

You will be given the project's files. Review them for correctness, readability, \
duplication, obvious bugs, and basic security issues.

Rules:
- Be practical, this is an MVP -- do not demand production-grade infrastructure.
- Respond ONLY with valid JSON, no markdown fences, no preamble.
- The example below is a JSON SHAPE only -- "app.py" and "short description" are
  placeholders. Use real file names and real, specific issue descriptions from the
  files you were actually given.
- Format:
{
  "approved": true,
  "issues": [
    {"file": "<REAL FILE PATH>", "severity": "warning", "note": "<THE ACTUAL ISSUE, SPECIFIC TO THIS CODE>"}
  ]
}
- Set "approved" to false only for real bugs or security problems, not style nitpicks.
- If there are no real issues, return an empty issues list.
"""


def review(existing_files: dict) -> dict:
    context_lines = []
    for path, content in existing_files.items():
        context_lines.append(f"--- {path} ---\n{content}")
    context = "\n\n".join(context_lines)

    return call_claude_json(
        system=REVIEWER_SYSTEM_PROMPT,
        user_message=f"Files to review:\n\n{context}",
        max_tokens=2000,
        role="reasoning",
    )
