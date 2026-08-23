"""
Permission guard (PDF section 21/23: "Tool Gateway" + human-approval layer).
Sits in front of every command that reaches the terminal or sandbox and
blocks anything destructive or deploy-shaped BEFORE it runs -- as a hard,
non-LLM rule, so a bad debugger patch or a prompt-injected file can't
talk its way past it.

This MVP has no real production target, so anything in the "needs human
approval" bucket is simply blocked rather than queued -- there's nothing
safe to approve into yet.

PDF section 24 addition -- per-agent permission matrix:
The blocked-pattern list above is a global floor everyone is subject to.
On top of it, PERMISSION_MATRIX encodes the table from section 24 (which
agent role may use which capability at all) as a second, independent
check. Passing agent=None (the default) skips the matrix entirely, so
every existing caller keeps its exact old behavior -- this is additive,
not a breaking change to callers that don't know about agent roles yet.
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

# Capabilities: "files_read", "files_write", "shell", "network", "deploy_staging",
# "deploy_production". Mirrors the section 24 table's columns (Files/Shell/
# Network/Deploy), split a little finer since "Deploy" itself has two very
# different risk levels in this codebase (staging vs. production).
PERMISSION_MATRIX = {
    "architect":  {"files_read", "network"},
    "backend":    {"files_read", "files_write", "shell", "network"},
    "frontend":   {"files_read", "files_write", "shell", "network"},
    "database":   {"files_read", "files_write"},
    "tester":     {"files_read", "shell", "network"},
    "debugger":   {"files_read", "files_write", "shell"},
    "security":   {"files_read", "shell", "network"},
    "devops":     {"files_read", "files_write", "shell", "network", "deploy_staging"},
    "release":    {"files_read", "shell", "network", "deploy_staging", "deploy_production"},
    "reviewer":   {"files_read"},
}


def agent_capability(agent: str, capability: str) -> bool:
    """True if this agent role is allowed to use this capability at all."""
    return capability in PERMISSION_MATRIX.get(agent, set())


def check(command: str, agent: str = None, capability: str = None) -> dict:
    """Returns {"allowed": bool, "reason": str|None}. Never raises."""
    if agent is not None and capability is not None and not agent_capability(agent, capability):
        return {"allowed": False, "reason": f"agent '{agent}' is not permitted to use capability '{capability}'"}

    normalized = " ".join(command.strip().lower().split())
    for pattern, reason in BLOCKED_PATTERNS:
        if re.search(pattern, normalized):
            return {"allowed": False, "reason": reason}
    return {"allowed": True, "reason": None}


def guard(command: str, agent: str = None, capability: str = None) -> None:
    """Hard gate: raises PermissionError if the command is blocked."""
    result = check(command, agent=agent, capability=capability)
    if not result["allowed"]:
        raise PermissionError(f"Blocked command: {command!r} -- {result['reason']}")
