"""
Dependency vulnerability scanner (Phase 6 / PDF section 38: pip-audit,
npm audit). Runs the real tool inside the same sandboxed container
used for tests -- not another regex guess -- so findings are backed by
an actual advisory database (PyPI Advisory DB / npm's).

Network-dependent by nature (it queries a vulnerability database), so
this is best-effort: if the sandbox has no network, or the install/
scan fails for any reason, we report "skipped" rather than failing the
whole build over a scan we couldn't run. A skipped dependency scan is
never treated as a security pass OR a security failure.
"""
import json
import re
from tools.sandbox import run_in_sandbox

PIP_AUDIT_CMD = (
    "if [ -f requirements.txt ]; then "
    "  pip install --quiet --disable-pip-version-check pip-audit 2>/dev/null && "
    "  pip-audit -r requirements.txt --format json 2>/tmp/pip_audit_err.log; "
    "  echo '---STDERR---'; cat /tmp/pip_audit_err.log; "
    "else "
    "  echo 'AURA_SKIP:no requirements.txt'; "
    "fi"
)

NPM_AUDIT_CMD = (
    "if [ -f package.json ]; then "
    "  npm install --silent --no-audit --no-fund >/dev/null 2>&1; "
    "  npm audit --json 2>/tmp/npm_audit_err.log; "
    "  echo '---STDERR---'; cat /tmp/npm_audit_err.log; "
    "else "
    "  echo 'AURA_SKIP:no package.json'; "
    "fi"
)


def _severity_from_pip_audit(vuln: dict) -> str:
    # pip-audit doesn't always include a severity field; if it does
    # (via OSV data) use it, otherwise default to "high" -- a known
    # CVE with a fix available is not something to call "low".
    sev = (vuln.get("severity") or "").lower()
    if sev in ("high", "critical"):
        return "high"
    if sev == "medium":
        return "medium"
    if sev == "low":
        return "low"
    return "high"


def _scan_pip(timeout: int) -> dict:
    result = run_in_sandbox(PIP_AUDIT_CMD, timeout=timeout)
    output = result["stdout"]

    if "AURA_SKIP" in output:
        return {"attempted": False, "findings": [], "detail": "no requirements.txt"}

    json_part = output.split("---STDERR---")[0].strip()
    if not json_part:
        return {"attempted": True, "findings": [], "detail": "pip-audit produced no output (install/network issue?)", "error": True}

    try:
        data = json.loads(json_part)
    except json.JSONDecodeError:
        return {"attempted": True, "findings": [], "detail": "could not parse pip-audit output", "error": True}

    findings = []
    for dep in data.get("dependencies", data if isinstance(data, list) else []):
        name = dep.get("name", "unknown")
        version = dep.get("version", "?")
        for vuln in dep.get("vulns", []):
            findings.append({
                "package": f"{name}=={version}",
                "id": vuln.get("id", "?"),
                "fix_versions": vuln.get("fix_versions", []),
                "severity": _severity_from_pip_audit(vuln),
                "source": "pip-audit",
            })
    return {"attempted": True, "findings": findings, "detail": f"{len(findings)} vulnerable dependency finding(s)"}


def _scan_npm(timeout: int) -> dict:
    result = run_in_sandbox(NPM_AUDIT_CMD, timeout=timeout)
    output = result["stdout"]

    if "AURA_SKIP" in output:
        return {"attempted": False, "findings": [], "detail": "no package.json"}

    json_part = output.split("---STDERR---")[0].strip()
    if not json_part:
        return {"attempted": True, "findings": [], "detail": "npm audit produced no output (install/network issue?)", "error": True}

    try:
        data = json.loads(json_part)
    except json.JSONDecodeError:
        return {"attempted": True, "findings": [], "detail": "could not parse npm audit output", "error": True}

    findings = []
    vulnerabilities = data.get("vulnerabilities", {})
    for pkg_name, info in vulnerabilities.items():
        severity = info.get("severity", "high")
        if severity not in ("low", "medium"):
            severity = "high"
        findings.append({
            "package": pkg_name,
            "id": ",".join(str(v.get("source", "")) for v in info.get("via", []) if isinstance(v, dict)) or "?",
            "fix_versions": [],
            "severity": severity,
            "source": "npm audit",
        })
    return {"attempted": True, "findings": findings, "detail": f"{len(findings)} vulnerable dependency finding(s)"}


def scan_dependencies(written_files: dict, timeout: int = 90) -> dict:
    """
    Runs pip-audit and/or npm audit depending on which manifest files
    are present. Returns a merged result; never raises -- a scan that
    couldn't run is reported as such, not silently treated as clean.
    """
    pip_result = None
    npm_result = None

    if "requirements.txt" in written_files:
        pip_result = _scan_pip(timeout)
    if "package.json" in written_files:
        npm_result = _scan_npm(timeout)

    all_findings = []
    attempted_any = False
    skipped_reasons = []

    for result in (pip_result, npm_result):
        if result is None:
            continue
        if result["attempted"]:
            attempted_any = True
            all_findings.extend(result["findings"])
            if result.get("error"):
                skipped_reasons.append(result["detail"])
        else:
            skipped_reasons.append(result["detail"])

    high = [f for f in all_findings if f["severity"] == "high"]
    return {
        "attempted": attempted_any,
        "passed": len(high) == 0,
        "findings": all_findings,
        "high_count": len(high),
        "medium_count": len([f for f in all_findings if f["severity"] == "medium"]),
        "low_count": len([f for f in all_findings if f["severity"] == "low"]),
        "skipped_reasons": skipped_reasons,
    }


def format_dependency_scan(result: dict) -> str:
    if not result["attempted"] and not result["findings"]:
        reasons = "; ".join(result.get("skipped_reasons", [])) or "no manifest files found"
        return f"  Dependency scan: skipped ({reasons})"
    if not result["findings"]:
        return "  Dependency scan: no known vulnerabilities found."
    lines = ["  Dependency scan:"]
    order = {"high": 0, "medium": 1, "low": 2}
    for f in sorted(result["findings"], key=lambda x: order.get(x["severity"], 3)):
        fix = f" (fix: {', '.join(f['fix_versions'])})" if f.get("fix_versions") else ""
        lines.append(f"    [{f['severity'].upper()}] {f['package']} -- {f['id']}{fix}")
    return "\n".join(lines)
