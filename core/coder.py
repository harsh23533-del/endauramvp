"""
Backend Engineer agent.
Given one create_file task (and the overall project goal for context),
generates backend code: routes, business logic, models, config,
scripts, tests.
"""
from core.llm import call_claude
from core.context_engine import get_relevant_context
from core.semantic_memory import get_knowledge

BACKEND_SYSTEM_PROMPT = """You are the Backend Engineer agent inside AURA, an autonomous \
software engineering system.

You will be given the overall project goal and ONE specific backend file to write.

Rules:
- Output ONLY the raw file content. No markdown fences, no explanation, no preamble.
- Code must be complete and runnable, not a sketch or placeholder.
- Keep it simple and correct -- this is an MVP.
- If writing a test file, use pytest and make sure imports match the actual file names.

""" + get_knowledge("backend")


def write_backend_code(project_goal: str, file_path: str, purpose: str, existing_files: dict) -> str:
    relevant_files = get_relevant_context(purpose, file_path, existing_files)
    context_lines = []
    for path, content in relevant_files.items():
        context_lines.append(f"--- {path} ---\n{content}")
    context = "\n\n".join(context_lines) if context_lines else "(no files written yet)"

    user_message = f"""Project goal: {project_goal}

File to write: {file_path}
Purpose of this file: {purpose}

Files already written in this project (for context/consistency):
{context}

Write the complete content of {file_path} now."""

    response_text = call_claude(
        system=BACKEND_SYSTEM_PROMPT,
        user_message=user_message,
        role="coding",
    )
    return _strip_markdown_fences(response_text)


def _strip_markdown_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    return cleaned


# Backward-compatible alias -- older code/tools may still import write_code.
write_code = write_backend_code
