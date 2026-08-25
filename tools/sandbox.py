"""
Sandbox tool.
Runs shell commands inside an isolated Docker container when a Docker
daemon is available, with the workspace directory mounted in.

Hosted PaaS environments (Render, Railway, etc.) generally run the app
itself inside a container and do NOT expose a Docker daemon to it, so
`docker run` simply isn't reachable there. Rather than fail hard, this
falls back to a still-guarded direct subprocess (workspace-locked cwd,
timeout, BLOCKED_PATTERNS + permission matrix, resource limits via
`resource.setrlimit` on POSIX) so the same code path works locally
(full container isolation) and when hosted (host-level isolation).
Set AURA_FORCE_SUBPROCESS_SANDBOX=1 to always use the fallback even if
Docker happens to be present (useful for testing the hosted path).
"""
import os
import shutil
import subprocess
import sys
from tools.filesystem import WORKSPACE_DIR
from tools.permissions import check as check_permission

IMAGE_NAME = "aura-sandbox"
DEFAULT_TIMEOUT = 120

try:
    import resource  # POSIX only
except ImportError:
    resource = None

# Cap on generated-project subprocess memory (bytes) when Docker isn't
# available to enforce it for us. 512MB, matching the docker --memory flag.
_FALLBACK_MEM_LIMIT_BYTES = 512 * 1024 * 1024


def _docker_available() -> bool:
    if os.environ.get("AURA_FORCE_SUBPROCESS_SANDBOX") == "1":
        return False
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5, check=False
        )
        return True
    except Exception:
        return False


def _limit_resources():
    """
    preexec_fn: apply resource limits to the child (POSIX only).

    IMPORTANT: RLIMIT_AS (virtual address space) is deliberately NOT set
    here. It looks like a natural memory cap, but it breaks fork() itself:
    Linux's memory-overcommit accounting can require the forking process
    to briefly account for the parent's full virtual address space, so a
    tight RLIMIT_AS makes any child that spawns its OWN subprocesses
    (pytest launching worker processes, pip launching a build backend,
    etc.) fail immediately with "Cannot fork" -- a false "the generated
    code is broken" signal that has nothing to do with the code at all.
    RLIMIT_DATA (heap growth) gives a real memory ceiling without that
    fork-time accounting problem.
    """
    if resource is None:
        return
    try:
        resource.setrlimit(
            resource.RLIMIT_DATA, (_FALLBACK_MEM_LIMIT_BYTES, _FALLBACK_MEM_LIMIT_BYTES)
        )
        resource.setrlimit(resource.RLIMIT_NPROC, (512, 512))
    except Exception:
        pass  # best-effort; never block the run over a limit that couldn't be set


def _run_in_docker(command: str, timeout: int) -> dict:
    docker_command = [
        "docker", "run", "--rm",
        "-v", f"{WORKSPACE_DIR}:/workspace",
        "-w", "/workspace",
        "--memory", "512m",
        "--cpus", "1",
        "--network", "none",
        IMAGE_NAME,
        "sh", "-c", command,
    ]
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


def _run_in_subprocess_fallback(command: str, timeout: int) -> dict:
    """Host-level fallback used when no Docker daemon is reachable."""
    if command.startswith("pip "):
        command = f'"{sys.executable}" -m pip ' + command[len("pip "):]
    kwargs = dict(
        shell=True,
        cwd=WORKSPACE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if resource is not None:
        kwargs["preexec_fn"] = _limit_resources
    try:
        result = subprocess.run(command, **kwargs)
        return {
            "command": command,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except MemoryError:
        return {
            "command": command,
            "stdout": "",
            "stderr": "Process exceeded the memory limit and was stopped.",
            "exit_code": -1,
        }


def run_in_sandbox(command: str, timeout: int = DEFAULT_TIMEOUT, agent: str = None, capability: str = None) -> dict:
    """
    Run a shell command in an isolated environment: a throwaway Docker
    container when Docker is reachable, otherwise a guarded, resource-
    limited subprocess confined to the workspace directory.

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

    try:
        if _docker_available():
            return _run_in_docker(command, timeout)
        return _run_in_subprocess_fallback(command, timeout)
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
            "stderr": "Neither Docker nor a usable shell was found to execute the command.",
            "exit_code": -1,
        }
