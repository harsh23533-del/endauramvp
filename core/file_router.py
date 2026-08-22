"""
File router.
Decides whether a planned file belongs to the Backend Engineer or the
Frontend Engineer, so each gets a specialist agent instead of one
generic Coder writing everything (PDF sections 9 & 10).
"""
import os

_FRONTEND_EXTENSIONS = {
    ".html", ".htm", ".css", ".scss", ".sass",
    ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
}

# Paths that are unambiguously frontend even with a generic extension
# (e.g. a "templates/" or "static/" folder in a Flask/Django project).
_FRONTEND_PATH_HINTS = ("templates/", "static/", "frontend/", "public/", "src/components/")


def classify(file_path: str) -> str:
    """Returns 'frontend' or 'backend' for a given planned file path."""
    normalized = file_path.replace("\\", "/").lower()
    _, ext = os.path.splitext(normalized)

    if ext in _FRONTEND_EXTENSIONS:
        return "frontend"
    if any(normalized.startswith(hint) or f"/{hint}" in normalized for hint in _FRONTEND_PATH_HINTS):
        return "frontend"
    return "backend"
