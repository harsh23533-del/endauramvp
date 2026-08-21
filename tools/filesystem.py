"""
File tools for AURA agents.
All paths are restricted to the WORKSPACE_DIR so agents can never
touch files outside the sandbox.
"""

import os

WORKSPACE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "workspace")
)


def _safe_path(relative_path: str) -> str:
    """Resolve a path and make sure it stays inside the workspace."""
    full_path = os.path.abspath(os.path.join(WORKSPACE_DIR, relative_path))
    if not full_path.startswith(WORKSPACE_DIR):
        raise ValueError(f"Path escapes workspace: {relative_path}")
    return full_path


def write_file(relative_path: str, content: str) -> str:
    path = _safe_path(relative_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return f"WROTE {relative_path} ({len(content)} chars)"


def read_file(relative_path: str) -> str:
    path = _safe_path(relative_path)
    with open(path, "r") as f:
        return f.read()


def list_files(relative_dir: str = ".") -> list[str]:
    path = _safe_path(relative_dir)
    results = []
    for root, _dirs, files in os.walk(path):
        for name in files:
            full = os.path.join(root, name)
            results.append(os.path.relpath(full, WORKSPACE_DIR))
    return sorted(results)


def ensure_workspace():
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
