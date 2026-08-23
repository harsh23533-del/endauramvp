"""
Debugger agent.
Given a test failure, analyzes root cause and produces patched files.
"""
from core.llm import call_claude_json
from core.context_engine import get_relevant_context

DEBUGGER_SYSTEM_PROMPT = """You are the Debugger agent inside AURA, an autonomous \
software engineering system.

You will be given the current contents of all project files and the output of a \
failed test run. Find the root cause and fix it.

Rules:
- Only change what's necessary to fix the failure.
- Respond ONLY with valid JSON, no markdown fences, no preamble.
- Format:
{
  "root_cause": "<THE ACTUAL ROOT CAUSE FROM THE TEST OUTPUT AND FILES YOU WERE GIVEN>",
  "patches": {
    "path/to/file.py": "COMPLETE new content of this file"
  }
}
- Include a file in "patches" only if you are changing it.
- Each file's content must be the COMPLETE new file, not a diff.
"""


def debug(user_request: str, existing_files: dict, test_output: str) -> dict:
    # Section 40's own example is a debugging task ("Fix login bug ->
    # auth/*.py + the stack trace, not the whole repo") -- the failing
    # test's output IS the signal for which files are actually relevant.
    relevant_files = get_relevant_context(test_output, "", existing_files, max_files=8)
    context_lines = []
    for path, content in relevant_files.items():
        context_lines.append(f"--- {path} ---\n{content}")
    context = "\n\n".join(context_lines)

    user_message = f"""Project goal: {user_request}

Current files:
{context}

Failed test output:
{test_output}

Diagnose the root cause and provide patches."""

    return call_claude_json(
        system=DEBUGGER_SYSTEM_PROMPT,
        user_message=user_message,
        max_tokens=6000,
        role="reasoning",
    )
