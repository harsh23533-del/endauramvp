"""
Existing-repo audit mode (PDF section 9 / phase 9).
Given a path to an existing local repository, read its files and
produce a prioritized engineering audit -- read-only, no writes, no
commands. This is the "analyze this repository and tell me what's
wrong with it" mode, not the full clone -> patch -> PR pipeline.
"""
import os
from core.llm import call_claude_json

AUDIT_SYSTEM_PROMPT = """You are the Repository Auditor agent inside AURA. You are \
given the contents of an existing codebase. You do NOT modify anything and you do \
NOT invent files or behavior you weren't shown.

Produce an engineering audit: what the project does, how it's structured, and a \
prioritized list of concrete problems (bugs, missing tests, security issues, poor \
error handling, unclear architecture, missing validation).

Rules:
- Respond ONLY with valid JSON, no markdown fences, no preamble.
- The example below shows the JSON SHAPE only -- every value in it is a placeholder you
  must replace with real content from the actual files you were given. Never return
  the placeholder text itself.
- Format:
{
  "summary": "<ONE PARAGRAPH: WHAT THIS SPECIFIC PROJECT DOES AND HOW IT'S STRUCTURED>",
  "findings": [
    {"area": "security", "severity": "high", "note": "<THE ACTUAL PROBLEM YOU FOUND, SPECIFIC TO A REAL FILE>", "file": "<REAL FILE PATH, OR OMIT THIS KEY IF UNKNOWN>"}
  ]
}
- severity is one of: high, medium, low.
- Prioritize findings with real impact over style nitpicks.
- If you cannot tell what a file does from a truncated excerpt, say so instead of guessing.
- If you have no real findings, return an empty findings list -- do not fill it with
  the example above.
"""

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", "workspace"}
TEXT_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".yml", ".yaml", ".txt", ".html", ".css"}
MAX_FILES = 40
MAX_FILE_CHARS = 4000
MAX_TOTAL_CHARS = 60000

# Weaker free-tier models occasionally echo the prompt's own JSON example
# back verbatim instead of filling it in with real content -- seen live
# with "short description" / "path/if/known" returned unchanged. These
# are the exact placeholder strings from the prompt above; anything that
# matches one gets dropped rather than shown to the user as a real finding.
_PLACEHOLDER_NOTES = {"short description", "the actual problem you found, specific to a real file"}
_PLACEHOLDER_FILES = {"path/if/known", "real file path, or omit this key if unknown"}
_PLACEHOLDER_SUMMARIES = {
    "one paragraph on what this project is and how it's built",
    "one paragraph: what this specific project does and how it's structured",
}


def collect_files(repo_path: str) -> dict:
    collected = {}
    total_chars = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in sorted(files):
            if len(collected) >= MAX_FILES or total_chars >= MAX_TOTAL_CHARS:
                return collected
            ext = os.path.splitext(name)[1]
            if ext not in TEXT_EXTENSIONS:
                continue
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, repo_path)
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(MAX_FILE_CHARS)
            except OSError:
                continue
            collected[rel_path] = content
            total_chars += len(content)
    return collected


def audit(repo_path: str) -> dict:
    if not os.path.isdir(repo_path):
        raise FileNotFoundError(f"Not a directory: {repo_path}")

    files = collect_files(repo_path)
    if not files:
        return {"summary": "No readable source files found.", "findings": [], "files_scanned": 0}

    context = "\n\n".join(f"--- {path} ---\n{content}" for path, content in files.items())

    result = call_claude_json(
        system=AUDIT_SYSTEM_PROMPT,
        user_message=f"Repository files:\n\n{context}",
        max_tokens=3000,
        role="reasoning",
    )
    result["files_scanned"] = len(files)

    # Defense-in-depth against the placeholder-echo failure mode above --
    # even if a future prompt edit reintroduces natural-sentence examples,
    # this still catches a model copying them verbatim.
    if result.get("summary", "").strip().lower() in _PLACEHOLDER_SUMMARIES:
        result["summary"] = "(model did not produce a real summary for this repository)"
    real_findings = []
    for f in result.get("findings", []):
        note_is_placeholder = f.get("note", "").strip().lower() in _PLACEHOLDER_NOTES
        file_is_placeholder = f.get("file", "").strip().lower() in _PLACEHOLDER_FILES
        if note_is_placeholder and (not f.get("file") or file_is_placeholder):
            continue
        real_findings.append(f)
    result["findings"] = real_findings

    return result


def format_audit(result: dict) -> str:
    lines = [
        "=== REPOSITORY AUDIT ===",
        f"Files scanned: {result.get('files_scanned', 0)}",
        "",
        result.get("summary", ""),
        "",
    ]
    findings = result.get("findings", [])
    if not findings:
        lines.append("No significant findings.")
    else:
        order = {"high": 0, "medium": 1, "low": 2}
        for f in sorted(findings, key=lambda x: order.get(x.get("severity"), 3)):
            file_part = f" [{f.get('file')}]" if f.get("file") else ""
            lines.append(f"  [{f.get('severity', '?').upper()}]{file_part} {f.get('note', '')}")
    lines.append("========================")
    return "\n".join(lines)
