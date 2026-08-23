"""
Deployment Agent -- Phase 8b.
Closes the gap the state machine already promised (section 42:
"... -> APPROVAL -> DEPLOYED") but the orchestrator never actually
reached: up through Phase 7 a release-ready, human-approved build
only got merged to the workspace's local main branch. Nothing was
ever "deployed".

Pipeline (section 20 / section 23):
  build_image -> deploy_staging -> validate -> deploy_production
Production is only attempted if staging deployed AND its health
check validated AND a human approved the release -- see
tools/deployment.py for the actual gate logic. This agent's job is
just to run that sequence and produce one clear, reportable result.
"""
from tools.deployment import build_image, deploy_staging, deploy_production


def run_deployment(project_name: str, written_files: dict, runtime_result: dict, human_approved: bool) -> dict:
    image = build_image(project_name, written_files)
    staging = deploy_staging(image, runtime_result)
    production = deploy_production(staging, bool(human_approved))

    if production["deployed"]:
        stage = "PRODUCTION"
    elif staging["deployed"]:
        stage = "STAGING_ONLY"
    else:
        stage = "NOT_DEPLOYED"

    return {
        "image": image,
        "staging": staging,
        "production": production,
        "stage": stage,
    }


def format_deployment(result: dict) -> str:
    lines = [f"DEPLOYMENT: {result['stage']}"]
    lines.append(f"  Image    : {result['image'].get('tag', 'n/a')}")
    lines.append(f"  Staging  : {'up' if result['staging']['deployed'] else 'not deployed'} -- {result['staging']['detail']}")
    lines.append(f"  Production: {'DEPLOYED' if result['production']['deployed'] else 'not deployed'} -- {result['production']['detail']}")
    return "\n".join(lines)
