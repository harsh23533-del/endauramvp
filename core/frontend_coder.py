"""
Frontend Engineer agent.
Given one create_file task, generates frontend code: HTML templates,
CSS, and client-side JS. Aware of the backend's API surface (routes
already written) so it doesn't blindly assume behavior (PDF section 10).
"""
from core.llm import call_claude
from core.coder import _strip_markdown_fences, _looks_like_reasoning_dump
from core.context_engine import get_relevant_context
from core.semantic_memory import get_knowledge

FRONTEND_SYSTEM_PROMPT = """You are the Frontend Engineer agent inside AURA, an autonomous \
software engineering system.

You will be given the overall project goal and ONE specific frontend file to write \
(HTML, CSS, or JS).

Rules:
- Output ONLY the raw file content. No markdown fences, no explanation, no preamble.
- Code must be complete and functional, not a sketch or placeholder.
- Keep it simple and correct -- this is an MVP, plain HTML/CSS/JS unless the project \
goal specifies a framework.
- If backend routes are visible in the existing files, call them with the correct \
paths and methods -- don't invent endpoints that don't exist.
- Keep markup semantic and reasonably accessible (labels on inputs, alt text on images).

""" + get_knowledge("frontend")


def write_frontend_code(project_goal: str, file_path: str, purpose: str, existing_files: dict,
                         retries: int = 2) -> str:
    relevant_files = get_relevant_context(purpose, file_path, existing_files)
    context_lines = []
    for path, content in relevant_files.items():
        context_lines.append(f"--- {path} ---\n{content}")
    context = "\n\n".join(context_lines) if context_lines else "(no files written yet)"

    user_message = f"""Project goal: {project_goal}

File to write: {file_path}
Purpose of this file: {purpose}

Files already written in this project (backend routes, other frontend files, etc):
{context}

Write the complete content of {file_path} now."""

    last_cleaned = None
    for attempt in range(retries + 1):
        response_text = call_claude(
            system=FRONTEND_SYSTEM_PROMPT,
            user_message=user_message,
            role="coding",
        )
        cleaned = _strip_markdown_fences(response_text)
        if not _looks_like_reasoning_dump(cleaned):
            return cleaned
        last_cleaned = cleaned

    # See core/coder.py's write_backend_code for why this raises instead
    # of writing the reasoning prose to disk -- same orchestrator-level
    # per-file skip-and-continue handling applies here too.
    raise RuntimeError(
        f"model kept returning chain-of-thought prose instead of {file_path}'s actual "
        f"content after {retries + 1} attempts (starts with: {last_cleaned[:120]!r})"
    )
