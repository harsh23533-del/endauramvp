"""
Sandbox tool.
Runs shell commands inside an isolated Docker container instead of the
host machine, with the workspace directory mounted in.
"""
import subprocess
from tools.filesystem import WORKSPACE_DIR
from tools.permissions import check as check_permission

IMAGE_NAME = "aura-sandbox"
DEFAULT_TIMEOUT = 120


def run_in_sandbox(command: str, timeout: int = DEFAULT_TIMEOUT, agent: str = None, capability: str = None) -> dict:
    """
    Run a shell command inside a throwaway Docker container.
    The workspace directory is mounted at /workspace inside the container.

    agent/capability are optional (PDF section 24) -- omitted means only
    the global BLOCKED_PATTERNS guard applies, unchanged from before.
    """
    permission = check_permission(command, agent=agent, capability=capability)
    if not permission["allowed"]:
        return {
            "command": command,
            "stdout": "",
            "stderr": f"BLOCKED: {permission['reason']}",
            "exit_code": -1,
        }

    docker_command = [
        "docker", "run", "--rm",
        "-v", f"{WORKSPACE_DIR}:/workspace",
        "-w", "/workspace",
        "--memory", "512m",
        "--cpus", "1",
        IMAGE_NAME,
        "sh", "-c", command,
    ]
    try:
        result = subprocess.run(
            docker_command,
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
    except FileNotFoundError:
        return {
            "command": command,
            "stdout": "",
            "stderr": "Docker not found. Install Docker Desktop and make sure it's running.",
            "exit_code": -1,
        }
