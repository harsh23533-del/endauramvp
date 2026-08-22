"""
Existing-repo audit mode.
Points AURA at a directory you already have and runs Security +
Reviewer + Critic against it -- read-only, no files are modified.
This is the first slice of "analyze an existing project" (PDF
section 47/51); it reports issues rather than opening a PR.

Usage:
    python audit_existing.py "C:\\path\\to\\project"
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from core.security import scan as security_scan
from core.reviewer import review
from core.critic import critique

_SKIP_DIRS = {".git", "venv", "env", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}
_MAX_FILE_BYTES = 50_000
_MAX_TOTAL_FILES = 60
_TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json",
    ".md", ".txt", ".yml", ".yaml", ".sql", ".sh",
}


def _collect_files(root_dir: str) -> dict:
    files = {}
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            _, ext = os.path.splitext(name)
            if ext.lower() not in _TEXT_EXTENSIONS:
                continue
            full_path = os.path.join(dirpath, name)
            rel_path = os.path.relpath(full_path, root_dir).replace("\\", "/")
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(_MAX_FILE_BYTES)
            except OSError:
                continue
            files[rel_path] = content
            if len(files) >= _MAX_TOTAL_FILES:
                return files
    return files


def audit(root_dir: str) -> dict:
    print(f"\n=== AURA: auditing existing project ===\n{root_dir}\n")
    if not os.path.isdir(root_dir):
        print(f"ERROR: '{root_dir}' is not a directory.")
        sys.exit(1)

    files = _collect_files(root_dir)
    print(f"Collected {len(files)} text files for review.\n")
    if not files:
        print("No reviewable text files found (check the path, or file extensions).")
        return {}

    print("--- Security: scanning files ---")
    security_result = security_scan(files)
    print(f"  security: {'PASS' if security_result['passed'] else 'ISSUES FOUND'}")
    for finding in security_result["findings"]:
        print(f"    [{finding['file']}:{finding['line']}] {finding['issue']}")

    print("\n--- Reviewer: reviewing code ---")
    try:
        review_result = review(files)
        print(f"  review: {'APPROVED' if review_result.get('approved') else 'CHANGES REQUESTED'}")
        for issue in review_result.get("issues", []):
            print(f"    [{issue.get('severity')}] {issue.get('file')}: {issue.get('note')}")
    except RuntimeError as e:
        print(f"  Reviewer could not complete: {e}")
        review_result = {"approved": None, "issues": [], "error": str(e)}

    print("\n--- Critic: looking for ways this breaks ---")
    try:
        critic_result = critique(files)
        print(f"  verdict: {critic_result.get('verdict')}")
        for b in critic_result.get("breaks_found", []):
            print(f"    [{b.get('file')}] {b.get('scenario')} -> {b.get('consequence')}")
    except RuntimeError as e:
        print(f"  Critic could not complete: {e}")
        critic_result = {"breaks_found": [], "verdict": "unknown", "error": str(e)}

    print("\n=== AUDIT SUMMARY ===")
    print(f"Files reviewed : {len(files)}")
    print(f"Security       : {'PASS' if security_result['passed'] else 'ISSUES'}")
    print(f"Review         : {'APPROVED' if review_result.get('approved') else 'CHANGES REQUESTED'}")
    print(f"Critic verdict : {critic_result.get('verdict')}")
    print("======================\n")
    print("Note: this is read-only -- no files were modified.")

    return {
        "files_reviewed": list(files.keys()),
        "security_result": security_result,
        "review_result": review_result,
        "critic_result": critic_result,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python audit_existing.py "path/to/existing/project"')
        sys.exit(1)
    audit(sys.argv[1])
