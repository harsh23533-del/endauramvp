"""
Git tool.
Gives each AURA-generated project its own commit history inside
workspace/ -- separate from AURA's own repo. Every meaningful build
stage becomes a checkpoint you can inspect or roll back to with
normal git commands, independent of AURA's in-memory regression
protection.

Phase 5 additions (PDF section 5 / section 31 "Git-based recovery"):
  - AURA now does its work on a feature branch, never directly on
    main (section 21: "never let an agent directly modify production").
  - A diff against main is available at any point, so the build
    report can show exactly what changed, not just a file list.
  - main only moves forward via merge_to_main(), and the orchestrator
    only calls that after the same release-gate/human-approval
    decision the rest of the pipeline already uses.

Note: each build starts from reset_workspace(), which wipes workspace/
(including .git) for a clean slate -- so "main" here is a fresh base
per build, not a history that survives across builds. That's by
design (see tools/filesystem.py); this module still gives every
single build real branch/diff/merge mechanics rather than committing
straight to main with no review point.
"""
import os
import re
import time
from tools.terminal import run_command
from tools.filesystem import WORKSPACE_DIR

_COMMIT_MSG_FILE = ".aura_commit_msg.tmp"
MAIN_BRANCH = "main"


def ensure_repo() -> None:
    """
    Initialize a git repo in workspace/ if one doesn't exist yet, with
    an empty initial commit on main -- gives create_build_branch() and
    diff_stat()/diff_full() a real base to branch from and diff
    against, instead of comparing against nothing.
    """
    if not os.path.isdir(os.path.join(WORKSPACE_DIR, ".git")):
        run_command("git init -q")
        run_command('git config user.email "aura@local"')
        run_command('git config user.name "AURA"')
        run_command(f"git checkout -q -b {MAIN_BRANCH}")
        run_command("git commit -q --allow-empty -m 'Initial empty commit'")


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


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].strip("-") or "build"


def current_branch() -> str:
    result = run_command("git rev-parse --abbrev-ref HEAD")
    return result["stdout"].strip() or MAIN_BRANCH


def create_build_branch(user_request: str) -> str:
    """
    Creates a feature branch for this build, named from the request
    plus a timestamp so repeated builds in the same workspace lifetime
    never collide. All coding/debugging happens here, not on main.
    """
    ensure_repo()
    branch_name = f"aura/{_slugify(user_request)}-{int(time.time())}"
    run_command(f"git checkout -q -b {branch_name}")
    return branch_name


def diff_stat(against: str = MAIN_BRANCH) -> str:
    """One-line-per-file summary of what changed on this branch vs. another ref."""
    result = run_command(f"git diff --stat {against}")
    return result["stdout"].strip() or "(no differences)"


def diff_full(against: str = MAIN_BRANCH, max_chars: int = 6000) -> str:
    """
    Full unified diff vs. another ref, truncated so a large build
    doesn't blow up the build report or an LLM context window.
    """
    result = run_command(f"git diff {against}")
    text = result["stdout"]
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... (truncated, {len(text) - max_chars} more chars)"
    return text.strip() or "(no differences)"


def merge_to_main(branch_name: str) -> dict:
    """
    Fast-forwards main to include this branch's work. Only meant to be
    called after the release gate (and, in --approve mode, a human)
    has said the build is good -- mirrors section 20's
    "AI decides/prepares -> deterministic gate -> approval -> merge"
    pattern, applied to git instead of a deploy pipeline.
    """
    run_command(f"git checkout -q {MAIN_BRANCH}")

    # Message written to a temp file and passed via -F, same pattern as
    # commit() -- avoids shell quoting differences (e.g. cmd.exe on
    # Windows doesn't treat single quotes as a string delimiter, which
    # let a stray "<branch>:" token leak through as an extra merge
    # argument and get resolved via git's <rev>:<path> tree syntax).
    msg_path = os.path.join(WORKSPACE_DIR, _COMMIT_MSG_FILE)
    with open(msg_path, "w", encoding="utf-8") as f:
        f.write(f"Merge {branch_name}: release-ready build")

    result = run_command(f"git merge -q --no-ff {branch_name} -F {_COMMIT_MSG_FILE}")
    os.remove(msg_path)
    return result
