"""
Debugger agent.
Given a test failure, analyzes root cause and produces patched files.
"""
import json
from core.llm import call_claude

DEBUGGER_SYSTEM_PROMPT = """You are the Debugger agent inside AURA, an autonomous \
software engineering system.

You will be given the current contents of all project files and the output of a \
failed test run. Find the root cause and fix it.

Rules:
- Only change what's necessary to fix the failure.
- Respond ONLY with valid JSON, no markdown fences, no preamble.
- Format:
{
  "root_cause": "short explanation",
  "patches": {
    "path/to/file.py": "COMPLETE new content of this file"
  }
}
- Include a file in "patches" only if you are changing it.
- Each file's content must be the COMPLETE new file, not a diff.
"""


def debug(user_request: str, existing_files: dict, test_output: str) -> dict:
    context_lines = []
    for path, content in existing_files.items():
        context_lines.append(f"--- {path} ---\n{content}")
    context = "\n\n".join(context_lines)

    user_message = f"""Project goal: {user_request}

Current files:
{context}

Failed test output:
{test_output}

Diagnose the root cause and provide patches."""

    response_text = call_claude(
        system=DEBUGGER_SYSTEM_PROMPT,
        user_message=user_message,
        max_tokens=6000,
    )
    cleaned = response_text.strip().strip("```").strip()
    if cleaned.startswith("json"):
        cleaned = cleaned[4:].strip()
    return json.loads(cleaned)