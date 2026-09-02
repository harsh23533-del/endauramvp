"""
Render deploy tool.

Thin wrapper around Render's public REST API (https://api.render.com/v1) --
NOT the Render MCP server (that only exists inside a Claude chat session;
this module is what the standalone AURA server calls at runtime, so it
talks to Render directly over HTTPS with a personal API key).

Auth: every call sends `Authorization: Bearer {RENDER_API_KEY}`, per
https://api-docs.render.com/reference/authentication.

This module only ever touches ONE service (found by name, created once
if missing) -- see core/live_deploy_agent.py for why: AURA builds run
one at a time, so one reused Render web service that gets redeployed
on every push mirrors the "single global workspace" model already used
for building, instead of accumulating a new service per build.
"""
import time
import requests

API_BASE = "https://api.render.com/v1"

# Known terminal Render deploy statuses (from Render's dashboard/docs).
# "live" is the only success state; everything else here means the
# deploy is done trying and did not end up live.
_FAILURE_STATUSES = {"build_failed", "update_failed", "canceled", "deactivated"}
_SUCCESS_STATUSES = {"live"}


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def find_service_by_name(api_key: str, name: str) -> dict | None:
    """Look up an existing service by exact name. None if not found."""
    resp = requests.get(
        f"{API_BASE}/services",
        headers=_headers(api_key),
        params={"name": name, "limit": 20},
        timeout=20,
    )
    resp.raise_for_status()
    for entry in resp.json():
        svc = entry.get("service", entry)  # list-services wraps each item as {"service": {...}, "cursor": ...}
        if svc.get("name") == name:
            return svc
    return None


def create_web_service(
    api_key: str,
    owner_id: str,
    name: str,
    repo: str,
    branch: str,
    build_command: str,
    start_command: str,
    region: str = "oregon",
    plan: str = "free",
) -> dict:
    """
    Create a new Python web service tracking `repo`/`branch`, with
    autoDeploy on (so every future push to that branch deploys itself --
    see core/live_deploy_agent.py, which relies on this and never calls
    trigger_deploy() after a push).
    """
    body = {
        "type": "web_service",
        "name": name,
        "ownerId": owner_id,
        "repo": repo,
        "branch": branch,
        "autoDeploy": "yes",
        "serviceDetails": {
            "env": "python",
            "plan": plan,
            "region": region,
            "envSpecificDetails": {
                "buildCommand": build_command,
                "startCommand": start_command,
            },
            "healthCheckPath": "/",
        },
    }
    resp = requests.post(f"{API_BASE}/services", headers=_headers(api_key), json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_service(api_key: str, service_id: str) -> dict:
    resp = requests.get(f"{API_BASE}/services/{service_id}", headers=_headers(api_key), timeout=20)
    resp.raise_for_status()
    return resp.json()


def latest_deploy(api_key: str, service_id: str) -> dict | None:
    """Most recent deploy for a service, or None if it has never deployed."""
    resp = requests.get(
        f"{API_BASE}/services/{service_id}/deploys",
        headers=_headers(api_key),
        params={"limit": 1},
        timeout=20,
    )
    resp.raise_for_status()
    items = resp.json()
    if not items:
        return None
    return items[0].get("deploy", items[0])


def trigger_deploy(api_key: str, service_id: str, clear_cache: bool = False) -> dict:
    """
    Only for services with autoDeploy off, or a manual redeploy with no
    new commit -- create_web_service() above always sets autoDeploy=yes
    and live_deploy_agent always pushes a new commit first, so in AURA's
    normal path the push itself triggers the deploy and this is never
    called (mirrors the Render MCP tool's own warning about this).
    """
    body = {"clearCache": "clear" if clear_cache else "do_not_clear"}
    resp = requests.post(f"{API_BASE}/services/{service_id}/deploys", headers=_headers(api_key), json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def poll_deploy(api_key: str, service_id: str, deploy_id: str, timeout_s: int = 420, interval_s: int = 6) -> dict:
    """
    Block (in the background worker thread, not the request thread --
    see how core/live_deploy_agent.run_live_deploy() is called) until
    the deploy reaches a terminal status or timeout_s elapses.
    """
    deadline = time.time() + timeout_s
    last = {"status": "unknown"}
    while time.time() < deadline:
        resp = requests.get(
            f"{API_BASE}/services/{service_id}/deploys/{deploy_id}",
            headers=_headers(api_key),
            timeout=20,
        )
        resp.raise_for_status()
        last = resp.json()
        status = last.get("status")
        if status in _SUCCESS_STATUSES or status in _FAILURE_STATUSES:
            return last
        time.sleep(interval_s)
    last["status"] = last.get("status", "timeout")
    return last


def service_url(service: dict) -> str | None:
    """
    Render returns a `url` field once a service has deployed at least
    once; before that, fall back to the predictable slug pattern (every
    free web service is public at https://{slug}.onrender.com).
    """
    if service.get("url"):
        return service["url"]
    slug = service.get("slug")
    return f"https://{slug}.onrender.com" if slug else None
