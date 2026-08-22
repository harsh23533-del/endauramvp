"""
Performance Engineer Agent (PDF section 13).
Static, deterministic checks for common performance foot-guns -- no LLM
call, so it's fast and never touches the rate limit.
"""

import re

CHECKS = [
    (r"for\s+\w+\s+in\s+.+:\s*\n\s+.*\.query\(", "Possible N+1 query pattern inside a loop"),
    (r"time\.sleep\(", "Blocking sleep() call -- avoid in request-handling code paths"),
    (r"\.readlines\(\)", "readlines() loads the whole file into memory -- fine for small files, risky for large ones"),
    (r"SELECT \* FROM", "SELECT * fetches all columns -- prefer explicit column lists at scale"),
]


def scan(existing_files: dict) -> dict:
    findings = []
    for path, content in existing_files.items():
        for pattern, note in CHECKS:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                line_no = content[:match.start()].count("\n") + 1
                findings.append({"file": path, "line": line_no, "issue": note})
    return {"passed": len(findings) == 0, "findings": findings}


def print_performance(result: dict) -> None:
    print("--- Performance: scanning files ---")
    if result["passed"]:
        print("  performance: PASS")
    else:
        print("  performance: ISSUES FOUND")
        for f in result["findings"]:
            print(f"    [{f['file']}:{f['line']}] {f['issue']}")
    print()
