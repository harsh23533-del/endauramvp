"""
Git tool.
Gives each AURA-generated project its own commit history inside
workspace/ -- separate from AURA's own repo. This means every
meaningful build stage becomes a checkpoint you can inspect or roll
back to with normal git commands, independent of AURA's in-memory
regression protection.
"""
import os
from tools.terminal import run_command
from tools.filesystem import WORKSPACE_DIR

_COMMIT_MSG_FILE = ".aura_commit_msg.tmp"


def ensure_repo() -> None:
    """Initialize a git repo in workspace/ if one doesn't exist yet."""
    if not os.path.isdir(os.path.join(WORKSPACE_DIR, ".git")):
        run_command("git init -q")
        run_command('git config user.email "aura@local"')
        run_command('git config user.name "AURA"')


def commit(message: str) -> dict:
    """
    Stage everything and commit, using --allow-empty so a checkpoint
    still lands even if this stage didn't change any files (keeps
    the history consistent and easy to read stage-by-stage).

    Commit message is written to a temp file and passed via -F
    instead of -m, so odd characters (quotes, newlines) in an
    LLM-generated message like a debugger's root_cause can't break
    the shell command.
    """
    ensure_repo()
    run_command("git add -A")

    msg_path = os.path.join(WORKSPACE_DIR, _COMMIT_MSG_FILE)
    with open(msg_path, "w", encoding="utf-8") as f:
        f.write(message)

    result = run_command(f"git commit -q --allow-empty -F {_COMMIT_MSG_FILE}")
    os.remove(msg_path)
    return result


def log(max_entries: int = 20) -> str:
    result = run_command(f"git log --oneline -{max_entries}")
    return result["stdout"].strip()


def revert_to(commit_hash: str) -> dict:
    """Hard-reset the workspace to a previous checkpoint. Destructive."""
    return run_command(f"git reset --hard {commit_hash}")
