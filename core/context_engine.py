"""
Context engineering (PDF section 40: "don't put the entire repository
into the LLM").

Before this, coder.py/frontend_coder.py passed the FULL existing_files
dict into every single generation call -- fine at MVP scale (a handful
of files) but exactly the anti-pattern section 40 warns against, and
it gets worse linearly as a project grows.

This is a lightweight, deterministic retrieval step (same keyword-
overlap approach core/traceability.py already uses for requirement
matching -- no extra LLM call needed just to decide what's relevant):
score every existing file against the current task's purpose + file
path, keep the top N, and always keep anything under a small size
threshold in full (small files are cheap to include and often config/
shared modules everything depends on).

This is not the "AST parser / symbol index / vector search" the PDF
describes -- that's real infrastructure this MVP doesn't need yet.
It's the same idea at MVP scale: stop sending files that clearly
aren't relevant to the current task.
"""
import re

_STOPWORDS = {"that", "with", "this", "shall", "should", "would", "have", "from", "into",
              "file", "write", "create", "project", "using", "should", "need", "needs"}

# Files at or under this size are cheap enough to just always include --
# skipping the relevance guesswork for small shared/config files.
ALWAYS_INCLUDE_MAX_CHARS = 400


def _keywords(text: str) -> set:
    words = re.findall(r"[a-zA-Z]{4,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def get_relevant_context(task_purpose: str, target_file_path: str, existing_files: dict, max_files: int = 6) -> dict:
    """
    Returns a subset of existing_files most relevant to the file about
    to be written, instead of the whole dict.

    - Files under ALWAYS_INCLUDE_MAX_CHARS are always kept (cheap, often shared/config).
    - Remaining files are scored by keyword overlap with task_purpose + target_file_path
      (path segments count too -- e.g. writing routes/expenses.py should pull in
      other expenses-* files even if the purpose text doesn't repeat the word).
    - If fewer than max_files remain after that, top-scoring files fill the rest.
    - If nothing scores above zero (e.g. very first file in a project), falls back
      to the most-recently-added files so there's still SOME continuity context.
    """
    if len(existing_files) <= max_files:
        return dict(existing_files)

    task_keywords = _keywords(task_purpose) | _keywords(target_file_path.replace("/", " ").replace("_", " "))

    always_include = {}
    scored = []
    for path, content in existing_files.items():
        if len(content) <= ALWAYS_INCLUDE_MAX_CHARS:
            always_include[path] = content
            continue
        path_keywords = _keywords(path.replace("/", " ").replace("_", " "))
        content_keywords = _keywords(content[:800])  # header/imports region is usually enough signal
        overlap = len(task_keywords & (path_keywords | content_keywords))
        scored.append((overlap, path, content))

    remaining_slots = max(0, max_files - len(always_include))
    scored.sort(key=lambda t: t[0], reverse=True)

    selected = dict(always_include)
    top = [t for t in scored if t[0] > 0][:remaining_slots]
    if not top and remaining_slots > 0:
        # Nothing scored -- fall back to the last-added files (dict insertion
        # order) rather than sending nothing extra.
        top = scored[-remaining_slots:]
    for _, path, content in top:
        selected[path] = content

    return selected
