"""
Security agent (Phase 6).
Runs deterministic static checks across project files -- no LLM call
needed, fast and repeatable. Findings are categorized roughly along
OWASP Top 10 lines (PDF section 16) and given a severity, so the
release gate can block on real risk (hardcoded secrets, injection)
without blocking on a "debug=True" left in a throwaway dev build.
"""
import re

# Each entry: (pattern, issue, category, severity)
# severity: "high" blocks release; "medium"/"low" are advisory only.
CHECKS = [
    # --- Secrets exposure ---
    (r"(?i)(api[_-]?key|secret|password|passwd)\s*=\s*[\"'][^\"']{6,}[\"']",
     "Possible hardcoded secret", "Secrets", "high"),
    (r"AKIA[0-9A-Z]{16}",
     "Looks like a hardcoded AWS access key ID", "Secrets", "high"),
    (r"-----BEGIN (RSA |EC |)PRIVATE KEY-----",
     "Hardcoded private key material", "Secrets", "high"),
    (r"\bxox[baprs]-[0-9A-Za-z-]{10,}",
     "Hardcoded Slack token", "Secrets", "high"),
    (r"\bghp_[A-Za-z0-9]{36}\b",
     "Hardcoded GitHub personal access token", "Secrets", "high"),

    # --- Injection ---
    (r"\beval\(",
     "Use of eval() is dangerous -- executes arbitrary code", "Injection", "high"),
    (r"\bexec\(",
     "Use of exec() is dangerous -- executes arbitrary code", "Injection", "high"),
    (r"\bos\.system\(",
     "os.system() with any untrusted input risks command injection", "Injection", "high"),
    (r"shell\s*=\s*True",
     "shell=True can enable command injection if input is untrusted", "Injection", "high"),
    (r"\.execute\(\s*f[\"']|\.execute\([^)]*%\s*[\"']|\.execute\([^)]*\+",
     "Building a SQL query with string formatting/concatenation risks SQL injection -- use parameterized queries",
     "Injection", "high"),

    # --- Insecure deserialization ---
    (r"\bpickle\.loads?\(",
     "pickle.load(s) on untrusted data can execute arbitrary code", "Insecure Deserialization", "high"),
    (r"\byaml\.load\((?!.*Loader=yaml\.SafeLoader)",
     "yaml.load() without SafeLoader can execute arbitrary code", "Insecure Deserialization", "high"),

    # --- Weak crypto ---
    (r"hashlib\.md5\(",
     "MD5 is not safe for passwords/security -- use bcrypt/argon2/scrypt", "Weak Crypto", "medium"),
    (r"hashlib\.sha1\(",
     "SHA1 is not safe for passwords/security -- use bcrypt/argon2/scrypt", "Weak Crypto", "medium"),

    # --- Broken access control / config exposure ---
    (r"debug\s*=\s*True",
     "Debug mode enabled -- unsafe for production (stack traces, code exposure)", "Configuration", "medium"),
    (r"ALLOWED_HOSTS\s*=\s*\[\s*[\"']\*[\"']\s*\]",
     "ALLOWED_HOSTS wildcard accepts any Host header", "Configuration", "medium"),
    (r"CORS.*[\"']\*[\"']|Access-Control-Allow-Origin.*\*",
     "Wildcard CORS origin allows any site to call this API", "Broken Access Control", "medium"),

    # --- XSS ---
    (r"\|\s*safe\b",
     "Jinja |safe filter disables autoescaping -- confirm the value is never user-controlled", "XSS", "medium"),
    (r"dangerouslySetInnerHTML",
     "dangerouslySetInnerHTML bypasses React's XSS protection -- sanitize input first", "XSS", "medium"),
]


def scan(existing_files: dict) -> dict:
    findings = []
    for path, content in existing_files.items():
        for pattern, issue, category, severity in CHECKS:
            for match in re.finditer(pattern, content):
                line_no = content[:match.start()].count("\n") + 1
                findings.append({
                    "file": path,
                    "line": line_no,
                    "issue": issue,
                    "category": category,
                    "severity": severity,
                })

    high = [f for f in findings if f["severity"] == "high"]
    return {
        # Only HIGH severity blocks the release gate -- medium/low are
        # advisory (surfaced in the report, not a build blocker).
        "passed": len(high) == 0,
        "findings": findings,
        "high_count": len(high),
        "medium_count": len([f for f in findings if f["severity"] == "medium"]),
        "low_count": len([f for f in findings if f["severity"] == "low"]),
    }


def format_security(result: dict) -> str:
    if not result["findings"]:
        return "  No issues found."
    lines = []
    order = {"high": 0, "medium": 1, "low": 2}
    for f in sorted(result["findings"], key=lambda x: order.get(x["severity"], 3)):
        lines.append(f"    [{f['severity'].upper()}][{f['category']}] {f['file']}:{f['line']} -- {f['issue']}")
    return "\n".join(lines)
