"""
Coder agent.
Given one create_file task (and the overall project goal for context),
generates the actual file content.
"""

from core.llm import call_claude

CODER_SYSTEM_PROMPT = """You are the Coder agent inside AURA, an autonomous \
software engineering system.

You will be given the overall project goal and ONE specific file to write.

Rules:
- Output ONLY the raw file content. No markdown fences, no explanation, no preamble.
- Code must be complete and runnable, not a sketch or placeholder.
- Keep it simple and correct — this is an MVP.
- If writing a test file, use pytest and make sure imports match the actual file names.
"""


def write_code(project_goal: str, file_path: str, purpose: str, existing_files: dict) -> str:
    context_lines = []
    for path, content in existing_files.items():
        context_lines.append(f"--- {path} ---\n{content}")
    context = "\n\n".join(context_lines) if context_lines else "(no files written yet)"

    user_message = f"""Project goal: {project_goal}

File to write: {file_path}
Purpose of this file: {purpose}

Files already written in this project (for context/consistency):
{context}

Write the complete content of {file_path} now."""

    response_text = call_claude(
        system=CODER_SYSTEM_PROMPT,
        user_message=user_message,
    )
    # Strip accidental markdown fences if the model adds them anyway
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    return cleaned
