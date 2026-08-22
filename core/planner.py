"""
Planner agent.
Converts the user's natural-language request into a short, concrete
list of build tasks (files to create, commands to run).
"""
import json
from core.llm import call_claude_json

PLANNER_SYSTEM_PROMPT = """You are the Planner agent inside AURA, an autonomous \
software engineering system.

Given a user's request, break it down into a short, concrete list of tasks \
needed to build a small, working version of it.

Rules:
- Keep it minimal -- this is an MVP, not a full product.
- Each task must be one of: "create_file" or "run_command".
- Prefer a single-file or few-file implementation when possible.
- Always include a task to write at least one test file using pytest.
- Always include a final "run_command" task that runs "pip install -r requirements.txt" \
if any third-party package is needed.
- If given an Architect's decision, follow the chosen stack.
- If given a requirements specification, make sure your tasks cover every \
functional requirement listed -- don't drop scope the Requirements Analyst identified.

Respond ONLY with valid JSON, no markdown fences, no preamble. Format:
{
  "tasks": [
    {"type": "create_file", "path": "app.py", "purpose": "Flask app with /hello route"},
    {"type": "create_file", "path": "requirements.txt", "purpose": "dependencies"},
    {"type": "create_file", "path": "test_app.py", "purpose": "pytest tests for /hello"},
    {"type": "run_command", "command": "pip install -r requirements.txt"}
  ]
}
"""


def plan(user_request: str, architecture: dict | None = None, requirements: dict | None = None) -> dict:
    context = ""
    if architecture:
        context += f"\n\nArchitect's decision: {json.dumps(architecture)}"
    if requirements:
        frs = requirements.get("functional_requirements", [])
        if frs:
            fr_lines = "\n".join(f"- {fr.get('id')}: {fr.get('description')}" for fr in frs)
            context += f"\n\nFunctional requirements to cover:\n{fr_lines}"

    return call_claude_json(
        system=PLANNER_SYSTEM_PROMPT,
        user_message=user_request + context,
    )
