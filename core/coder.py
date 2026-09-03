"""
Backend Engineer agent.
Given one create_file task (and the overall project goal for context),
generates backend code: routes, business logic, models, config,
scripts, tests.
"""
import re

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

# Heuristic safety net for models that leak chain-of-thought straight
# into their response content instead of a separate reasoning channel.
# core/llm.py's `reasoning: {"exclude": true}` request param is the
# real fix for this; these markers catch whatever slips through it
# anyway (checked against the START of the response only, since a
# legitimate file can obviously mention "analyze" deeper in a comment).
_REASONING_PREAMBLE_MARKERS = (
    "here's a thinking process", "here's my thinking", "here is my thinking",
    "let me think", "let's think step by step", "i need to analyze",
    "thinking process:", "let me start by", "okay, let me", "first, i need to",
    "let me break this down", "my thought process", "let me analyze",
)


def _looks_like_reasoning_dump(text: str) -> bool:
    # Require the marker at the very START of the response (not just
    # "appears somewhere in the first N chars") -- a leaked reasoning
    # dump always OPENS with one of these phrases, whereas a legitimate
    # file could easily contain one incidentally deeper in a comment or
    # docstring (e.g. "# let me think about caching later"). Using
    # startswith on a short head window avoids flagging that.
    head = text.strip()[:80].lower()
    return any(head.startswith(marker) for marker in _REASONING_PREAMBLE_MARKERS)


def write_backend_code(project_goal: str, file_path: str, purpose: str, existing_files: dict,
                        retries: int = 2) -> str:
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

    last_cleaned = None
    for attempt in range(retries + 1):
        response_text = call_claude(
            system=BACKEND_SYSTEM_PROMPT,
            user_message=user_message,
            role="coding",
        )
        cleaned = _strip_markdown_fences(response_text)
        if not _looks_like_reasoning_dump(cleaned):
            return cleaned
        last_cleaned = cleaned

    # Exhausted retries -- raise rather than silently write chain-of-
    # thought prose to disk as if it were the file's real content. The
    # orchestrator's per-file try/except already treats a RuntimeError
    # here as "skip this one file, log it, keep the rest of the build
    # going" (see its coder_failures handling), same as an LLM-call
    # failure.
    raise RuntimeError(
        f"model kept returning chain-of-thought prose instead of {file_path}'s actual "
        f"content after {retries + 1} attempts (starts with: {last_cleaned[:120]!r})"
    )


def _strip_markdown_fences(text: str) -> str:
    cleaned = text.strip()
    # Prefer the LAST fully-closed fenced block if one exists anywhere --
    # a model that thinks out loud before answering often still wraps
    # the final, real answer in a fence even when the preceding prose
    # isn't itself fenced (so "starts with ``` " alone would miss it).
    fence_blocks = re.findall(r"```[a-zA-Z0-9_+-]*\n(.*?)```", cleaned, re.DOTALL)
    if fence_blocks:
        return fence_blocks[-1].strip()
    # No fully-closed fence found -- if there's at least one opening
    # fence, take everything after the LAST one. Handles a response that
    # got cut off mid-code with no closing ``` at all (e.g. the model
    # burned most of its token budget on reasoning first).
    last_open = cleaned.rfind("```")
    if last_open != -1:
        after = cleaned[last_open + 3:]
        after = after.split("\n", 1)[1] if "\n" in after else after
        return after.strip()
    return cleaned


# Backward-compatible alias -- older code/tools may still import write_code.
write_code = write_backend_code
