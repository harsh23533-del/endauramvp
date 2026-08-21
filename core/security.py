"""
Security agent.
Runs simple static checks across project files -- no LLM call needed,
fast and deterministic.
"""
import re

CHECKS = [
    (r"(?i)(api_key|secret|password)\s*=\s*[\"'][^\"']{6,}[\"']", "Possible hardcoded secret"),
    (r"\beval\(", "Use of eval() is dangerous"),
    (r"\bexec\(", "Use of exec() is dangerous"),
    (r"debug\s*=\s*True", "Debug mode enabled -- unsafe for production"),
    (r"shell\s*=\s*True", "shell=True can enable command injection if input is untrusted"),
]


def scan(existing_files: dict) -> dict:
    findings = []
    for path, content in existing_files.items():
        for pattern, note in CHECKS:
            for match in re.finditer(pattern, content):
                line_no = content[:match.start()].count("\n") + 1
                findings.append({
                    "file": path,
                    "line": line_no,
                    "issue": note,
                })
    return {
        "passed": len(findings) == 0,
        "findings": findings,
    }