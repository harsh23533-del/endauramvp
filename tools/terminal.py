"""
Terminal tool for AURA agents.
Runs shell commands with the working directory locked to workspace/,
a timeout, and no shell metacharacter tricks (no `shell=True` with
untrusted string concatenation elsewhere in the codebase).
"""
import subprocess
import sys
from tools.filesystem import WORKSPACE_DIR
from tools.permissions import check as permission_check

DEFAULT_TIMEOUT = 60  # seconds


def run_command(command: str, timeout: int = DEFAULT_TIMEOUT, agent: str = None, capability: str = None) -> dict:
    """
    Run a shell command inside the workspace directory.
    Returns dict with stdout, stderr, and exit code.

    agent/capability are optional (PDF section 24's per-agent matrix) --
    when omitted, only the global BLOCKED_PATTERNS guard applies, same
    as before this parameter existed.
    """
    command = command.strip()

    permission = permission_check(command, agent=agent, capability=capability)
    if not permission["allowed"]:
        return {
            "command": command,
            "stdout": "",
            "stderr": f"BLOCKED by permission guard: {permission['reason']}",
            "exit_code": -1,
        }

    if command.startswith("pip "):
        command = f'"{sys.executable}" -m pip ' + command[len("pip "):]
    elif command.startswith("pytest"):
        command = f'"{sys.executable}" -m pytest' + command[len("pytest"):]
    elif command == "python" or command.startswith("python "):
        command = f'"{sys.executable}" ' + command[len("python"):].lstrip()

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "command": command,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "stdout": "",
            "stderr": f"TIMEOUT after {timeout}s",
            "exit_code": -1,
        }