"""
Live Deploy Agent.

Sits alongside (not instead of) the simulated build_image/deploy_staging/
deploy_production pipeline in deployment_agent.py -- that pipeline still
models the AI-prepares -> CI/CD -> approval-gate flow. This agent is the
concrete "make the validated build reachable at a real URL" step: it
pushes the generated project to a git repo and deploys it on Render via
Render's REST API (see tools/render_deploy.py), gated on the same signal
deploy_staging() uses (the app proved it can start locally) so nothing
ever goes public from a build that never even booted.

Fully optional: if RENDER_API_KEY / LIVE_DEPLOY_REPO / LIVE_DEPLOY_PUSH_TOKEN
aren't set, run_live_deploy() returns a clean "not configured" result --
it never raises, so a host that hasn't set this up just doesn't get a
live link, the rest of the build is unaffected.

Because server.py only ever runs one build at a time (its own module
docstring), this agent reuses ONE Render web service across builds --
each build force-pushes over the last one on a fixed branch, Render's
autoDeploy (always on for the service this creates) picks it up, and
the same public URL serves whichever build most recently finished. A
new build replacing the previous one's live preview is the accepted
tradeoff for a single shared demo instance, not a per-user host.
"""
import os
import shutil
import subprocess
import time

from tools.filesystem import WORKSPACE_DIR
from tools.permissions import agent_capability
from tools import render_deploy

_CHECKOUT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "live_deploy_checkout")
)
_SERVICE_NAME = os.environ.get("LIVE_DEPLOY_SERVICE_NAME", "aura-live-preview")
_BRANCH = os.environ.get("LIVE_DEPLOY_BRANCH", "live")


def _configured() -> tuple[bool, str]:
    missing = [
        var for var in ("RENDER_API_KEY", "LIVE_DEPLOY_REPO", "LIVE_DEPLOY_PUSH_TOKEN")
        if not os.environ.get(var)
    ]
    if missing:
        return False, f"live deploy not configured -- missing {', '.join(missing)}"
    return True, ""


def _run(args: list[str], cwd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _authed_remote_url(repo_url: str, push_token: str) -> str:
    """Embed the push token in the https:// remote URL, GitHub Actions-style."""
    if repo_url.startswith("https://") and "@" not in repo_url:
        return repo_url.replace("https://", f"https://x-access-token:{push_token}@", 1)
    return repo_url


def _sync_checkout(repo_url: str, push_token: str, branch: str) -> tuple[bool, str]:
    """
    Make _CHECKOUT_DIR a working tree of `repo_url` on `branch`, cloning
    fresh the first time and just fetching after that -- a persistent
    sibling of workspace/ so reset_workspace() (which wipes workspace/
    on every build) never touches it.
    """
    remote = _authed_remote_url(repo_url, push_token)
    if not os.path.isdir(os.path.join(_CHECKOUT_DIR, ".git")):
        if os.path.isdir(_CHECKOUT_DIR):
            shutil.rmtree(_CHECKOUT_DIR)
        result = _run(["git", "clone", remote, _CHECKOUT_DIR], cwd=os.path.dirname(_CHECKOUT_DIR), timeout=60)
        if result.returncode != 0:
            return False, f"git clone failed: {result.stderr[:300]}"
    else:
        _run(["git", "remote", "set-url", "origin", remote], cwd=_CHECKOUT_DIR, timeout=20)
        _run(["git", "fetch", "origin"], cwd=_CHECKOUT_DIR, timeout=60)

    _run(["git", "config", "user.email", "aura@local"], cwd=_CHECKOUT_DIR, timeout=10)
    _run(["git", "config", "user.name", "AURA"], cwd=_CHECKOUT_DIR, timeout=10)

    # Land on `branch` whether or not it exists on the remote yet.
    checkout = _run(["git", "checkout", "-B", branch, f"origin/{branch}"], cwd=_CHECKOUT_DIR, timeout=20)
    if checkout.returncode != 0:
        _run(["git", "checkout", "-B", branch], cwd=_CHECKOUT_DIR, timeout=20)
    return True, ""


def _replace_contents_with(written_files: dict) -> None:
    """Wipe everything in the checkout except .git, then write the new build's files."""
    for entry in os.listdir(_CHECKOUT_DIR):
        if entry == ".git":
            continue
        full = os.path.join(_CHECKOUT_DIR, entry)
        if os.path.isdir(full):
            shutil.rmtree(full)
        else:
            os.remove(full)
    for rel_path, content in written_files.items():
        dest = os.path.join(_CHECKOUT_DIR, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)


def _push(branch: str) -> tuple[bool, str]:
    _run(["git", "add", "-A"], cwd=_CHECKOUT_DIR, timeout=20)
    commit = _run(["git", "commit", "-q", "--allow-empty", "-m", "AURA live deploy"], cwd=_CHECKOUT_DIR, timeout=20)
    if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
        return False, f"git commit failed: {commit.stderr[:300]}"
    push = _run(["git", "push", "-f", "origin", branch], cwd=_CHECKOUT_DIR, timeout=60)
    if push.returncode != 0:
        return False, f"git push failed: {push.stderr[:300]}"
    return True, ""


def _build_start_commands(written_files: dict) -> tuple[str, str]:
    """
    AURA's generated projects are, at this MVP's current scope, always a
    single app.py Flask app (see core/runtime_agent.py's own health-check
    command, which makes the same assumption) -- so the build/start
    commands are fixed rather than guessed per-project. `gunicorn` is
    added here rather than to the generated requirements.txt, since this
    is a Render-specific production run step, not something that should
    change what the user actually downloads.
    """
    if "requirements.txt" in written_files:
        build_command = "pip install -r requirements.txt gunicorn"
    else:
        build_command = "pip install flask gunicorn"
    start_command = "gunicorn app:app --bind 0.0.0.0:$PORT"
    return build_command, start_command


def _ensure_service(api_key: str, owner_id: str, repo: str, branch: str, written_files: dict) -> dict:
    existing = render_deploy.find_service_by_name(api_key, _SERVICE_NAME)
    if existing:
        return existing
    build_command, start_command = _build_start_commands(written_files)
    created = render_deploy.create_web_service(
        api_key, owner_id, _SERVICE_NAME, repo, branch, build_command, start_command,
    )
    return created.get("service", created)


def run_live_deploy(written_files: dict, runtime_result: dict) -> dict:
    ok, reason = _configured()
    if not ok:
        return {"attempted": False, "deployed": False, "live_url": None, "detail": reason}

    if not agent_capability("release", "deploy_production"):
        return {"attempted": False, "deployed": False, "live_url": None,
                 "detail": "blocked -- no role holds deploy_production capability"}

    # Same gate tools/deployment.py's deploy_staging() uses: don't put
    # something public that never proved it can even start.
    if runtime_result.get("started") is not True:
        return {"attempted": False, "deployed": False, "live_url": None,
                 "detail": "skipped -- app did not pass its local runtime health check"}

    api_key = os.environ["RENDER_API_KEY"]
    repo = os.environ["LIVE_DEPLOY_REPO"]
    push_token = os.environ["LIVE_DEPLOY_PUSH_TOKEN"]
    owner_id = os.environ.get("RENDER_OWNER_ID", "")

    try:
        ok, detail = _sync_checkout(repo, push_token, _BRANCH)
        if not ok:
            return {"attempted": True, "deployed": False, "live_url": None, "detail": detail}

        _replace_contents_with(written_files)

        ok, detail = _push(_BRANCH)
        if not ok:
            return {"attempted": True, "deployed": False, "live_url": None, "detail": detail}

        service = _ensure_service(api_key, owner_id, repo, _BRANCH, written_files)
        service_id = service.get("id") or service.get("service", {}).get("id")
        if not service_id:
            return {"attempted": True, "deployed": False, "live_url": None,
                     "detail": f"could not resolve a Render service id from: {service}"}

        # autoDeploy is always "yes" on the service this agent creates,
        # and we just pushed a new commit, so a deploy starts on its own
        # -- give Render a moment to pick it up before polling for it.
        time.sleep(4)
        deploy = render_deploy.latest_deploy(api_key, service_id)
        if not deploy or not deploy.get("id"):
            return {"attempted": True, "deployed": False, "live_url": None,
                     "detail": "pushed, but no deploy showed up on the service yet"}

        result = render_deploy.poll_deploy(api_key, service_id, deploy["id"])
        status = result.get("status")
        service = render_deploy.get_service(api_key, service_id)
        url = render_deploy.service_url(service.get("service", service))

        if status == "live":
            return {"attempted": True, "deployed": True, "live_url": url,
                     "detail": f"live at {url}"}
        return {"attempted": True, "deployed": False, "live_url": url,
                 "detail": f"deploy ended with status '{status}'"}
    except Exception as e:  # noqa: BLE001 -- never let a live-deploy problem fail the whole build
        return {"attempted": True, "deployed": False, "live_url": None, "detail": f"error: {e}"}


def format_live_deploy(result: dict) -> str:
    if not result.get("attempted"):
        return f"LIVE DEPLOY: not attempted -- {result['detail']}"
    return f"LIVE DEPLOY: {'LIVE' if result['deployed'] else 'FAILED'} -- {result['detail']}"
