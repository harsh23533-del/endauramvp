"""
Release gate.
A deterministic pass/fail check that decides whether this build is
RELEASE_READY or BLOCKED -- combining test results, security findings,
review approval, and critic verdict into one clear decision. Some
states require an explicit gate, not just an average score (PDF
sections 21 & 42).
"""


def evaluate_release(report: dict) -> dict:
    reasons = []

    test_result = report.get("test_result", {})
    if not test_result.get("passed"):
        reasons.append("Tests are not passing.")

    security_result = report.get("security_result", {})
    if not security_result.get("passed", True):
        count = len(security_result.get("findings", []))
        reasons.append(f"{count} security finding(s) unresolved.")

    review_result = report.get("review_result", {})
    if review_result.get("approved") is False:
        reasons.append("Reviewer requested changes.")

    critic_result = report.get("critic_result", {})
    if critic_result.get("verdict") == "breaks_easily":
        reasons.append("Critic found the implementation breaks easily.")

    infra_error = report.get("infra_error")
    if infra_error:
        reasons.append(f"Infrastructure issue: {infra_error}")

    status = "BLOCKED" if reasons else "RELEASE_READY"
    return {"status": status, "reasons": reasons}


def format_release_gate(gate: dict) -> str:
    lines = [f"RELEASE GATE: {gate['status']}"]
    for r in gate["reasons"]:
        lines.append(f"  - {r}")
    if gate["status"] == "RELEASE_READY":
        lines.append("  All checks passed. Still requires human approval to actually deploy.")
    return "\n".join(lines)
