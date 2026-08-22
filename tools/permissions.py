"""
Permission guard (PDF section 21/23: "Tool Gateway" + human-approval layer).
Sits in front of every command that reaches the terminal or sandbox and
blocks anything destructive or deploy-shaped BEFORE it runs -- as a hard,
non-LLM rule, so a bad debugger patch or a prompt-injected file can't
talk its way past it.

This MVP has no real production target, so anything in the "needs human
approval" bucket is simply blocked rather than queued -- there's nothing
safe to approve into yet.
"""
import re

BLOCKED_PATTERNS = [
    (r"rm\s+-rf\s+/(?!\S)", "rm -rf / -- would wipe the filesystem"),
    (r"rm\s+-rf\s+\*", "rm -rf * -- recursive wildcard delete"),
    (r"\bdrop\s+database\b", "DROP DATABASE"),
    (r"\bdrop\s+table\b", "DROP TABLE"),
    (r"\btruncate\s+table\b", "TRUNCATE TABLE"),
    (r"git\s+push[^\n]*--force", "force push can overwrite remote history"),
    (r"git\s+reset\s+--hard\s+origin", "hard reset against origin is destructive"),
    (r"\bsudo\b", "sudo -- privilege escalation not allowed in the sandbox"),
    (r"\bmkfs\b", "mkfs -- formats a filesystem"),
    (r":\(\)\s*\{[^}]*\};\s*:", "fork bomb pattern"),
    (r"\bshutdown\b|\breboot\b", "shutdown/reboot -- host control, not allowed"),
    (r"\bdeploy\b[^\n]*\bproduction\b|\bproduction\b[^\n]*\bdeploy\b", "production deployment requires human approval"),
    (r"curl[^\n]*\|\s*(sh|bash)\b", "piping a remote script into a shell is unreviewable code execution"),
    (r"\bwget\b[^\n]*\|\s*(sh|bash)\b", "piping a remote script into a shell is unreviewable code execution"),
]


def check(command: str) -> dict:
    """Returns {"allowed": bool, "reason": str|None}. Never raises."""
    normalized = " ".join(command.strip().lower().split())
    for pattern, reason in BLOCKED_PATTERNS:
        if re.search(pattern, normalized):
            return {"allowed": False, "reason": reason}
    return {"allowed": True, "reason": None}


def guard(command: str) -> None:
    """Hard gate: raises PermissionError if the command is blocked."""
    result = check(command)
    if not result["allowed"]:
        raise PermissionError(f"Blocked command: {command!r} -- {result['reason']}")
