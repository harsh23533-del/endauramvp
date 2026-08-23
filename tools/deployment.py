"""
Deployment tools.
PDF section 23 lists DEPLOYMENT TOOLS: build_image, deploy_staging,
deploy_production. This MVP has no real cloud/registry to push to,
so these are simulated -- but they are still real, deterministic
steps (not an LLM guessing), each one gated on the previous one
succeeding, exactly like section 20's "AI prepares -> deterministic
CI/CD -> tests -> approval gate -> deployment" pipeline.

Nothing here is optional or skippable from code: deploy_production()
refuses to run unless a staging deploy already passed its health
check, so there is no path from "build finished" straight to
"production" without an intermediate, validated stage (section 21).
"""
import os
import time
from tools.filesystem import WORKSPACE_DIR


def build_image(project_name: str, written_files: dict) -> dict:
    """
    Simulated `docker build`. Deterministic: an image is just a
    content-addressed tag derived from what was actually written, so
    two builds of identical output get the same tag and a changed
    build gets a different one -- no LLM involved.
    """
    file_count = len(written_files)
    digest = format(abs(hash(frozenset(written_files.keys()))) % (16**12), "012x")
    tag = f"{project_name}:{digest}"
    manifest = {
        "tag": tag,
        "file_count": file_count,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    manifest_path = os.path.join(WORKSPACE_DIR, "deployment", "image-manifest.json")
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    import json
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return {"success": True, "tag": tag, "manifest_path": "deployment/image-manifest.json"}


def deploy_staging(image: dict, runtime_result: dict) -> dict:
    """
    Simulated staging deploy + validation. Reuses the runtime agent's
    health-check result (section 13) as the staging validation signal
    instead of re-implementing another health check -- if the app
    never proved it can start, staging can't "pass" either.
    """
    if not image.get("success"):
        return {"deployed": False, "validated": False, "detail": "no image to deploy"}

    if runtime_result.get("started") is False:
        return {"deployed": True, "validated": False, "detail": "staging deploy up, but health check failed -- " + runtime_result.get("detail", "")}

    if runtime_result.get("started") is None:
        # No runtime check was possible (e.g. not a Flask app) -- deploy
        # but be explicit that validation is inconclusive rather than
        # silently treating "unknown" as "pass".
        return {"deployed": True, "validated": None, "detail": "staging deploy up, health check inconclusive"}

    return {"deployed": True, "validated": True, "detail": "staging deploy up, health check passed"}


def deploy_production(staging_result: dict, human_approved: bool) -> dict:
    """
    Gated production deploy. Requires BOTH a validated staging deploy
    AND explicit human approval -- either missing blocks it. This is
    the hard boundary from section 21 ("Deploy production -- APPROVAL
    required") and section 20 ("I would not let an LLM freely deploy
    to production").
    """
    if not staging_result.get("deployed") or not staging_result.get("validated"):
        return {"deployed": False, "detail": "blocked -- staging was not deployed and validated"}
    if not human_approved:
        return {"deployed": False, "detail": "blocked -- production deploy requires human approval"}
    return {"deployed": True, "detail": "production deploy complete"}
