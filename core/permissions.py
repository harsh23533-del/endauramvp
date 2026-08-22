"""
Permission guard.
Lightweight defense-in-depth check before any sandboxed command runs
-- blocks obviously destructive patterns regardless of which agent
generated them. Some operations should never be auto-allowed, no
matter how the request was framed (PDF sections 21 & 24).
"""
import re

_DESTRUCTIVE_PATTERNS = [
    re.compile(r"rm\s+-rf\s+/(?!\S)"),        # rm -rf /
    re.compile(r"rm\s+-rf\s+/\*"),            # rm -rf /*
    re.compile(r":\(\)\s*\{.*:\|:.*\}\s*;\s*:"),  # shell fork bomb
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s+if=.*of=/dev/"),
    re.compile(r"chmod\s+-R\s+777\s+/(?!\S)"),
    re.compile(r">\s*/dev/sd[a-z]"),
]


def is_destructive(command: str) -> bool:
    """Returns True if the command matches a known-destructive pattern."""
    return any(pattern.search(command) for pattern in _DESTRUCTIVE_PATTERNS)
