"""
Pull Request Agent -- Phase 9 (PDF section 48 / section 51).

core/audit_agent.py already covered step 1 of "existing repository
mode" -- read-only understand + findings. This module is the rest of
the pipeline that section 51 actually describes:

    Repository -> Understand -> Map problems -> Plan -> Implement
    -> Test -> Security -> Review -> Pull Request

It reuses audit_agent.audit() and collect_files() rather than
re-implementing "read the repo", and reuses the same security.scan()
the main build pipeline uses -- one security checker, not two.

Safety boundaries (section 21 / section 48, applied to a REAL repo
this time, not a disposable workspace/):
  - Never commits to the repo's current/default branch. All work
    happens on a new aura/fix-* branch, always.
  - A PR is only opened if the fix's own tests pass AND no new
    high-severity security finding was introduced. Otherwise the
    branch + commit are left for a human to inspect manually.
  - If `gh` (GitHub CLI) isn't installed/authenticated, or the repo
    has no push access, this stops at "branch ready" and says so --
    it never guesses at credentials or silently skips the gate.
"""
import os
import subprocess
import time
from core.audit_agent import audit, format_audit, collect_files
from core.security import scan as security_scan, format_security
from core.llm import call_claude_json

FIX_SYSTEM_PROMPT = """You are the Fix Engineer agent inside AURA, working against an \
EXISTING codebase (not generating a new one from scratch).

You are given the current contents of the repository's files and ONE specific finding \
to fix.

Rules:
- Only change what's necessary to address this finding. Do not rewrite unrelated code
  or reformat files you aren't fixing.
- Respond ONLY with valid JSON, no markdown fences, no preamble.
- Format:
{
  "explanation": "what you changed and why, in 1-3 sentences",
  "patches": {"path/to/file.py": "COMPLETE new content of this file"}
}
- Each file's content must be the COMPLETE new file, not a diff or snippet.
- Only include files you are actually changing. If you cannot safely fix this without
  more context, return an empty "patches" object and explain why in "explanation".
"""

MAX_FIXES_PER_RUN = 2


def _run(cmd: str, cwd: str, timeout: int = 60) -> dict:
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"TIMEOUT after {timeout}s", "exit_code": -1}


def _detect_test_command(repo_path: str) -> str:
    if os.path.exists(os.path.join(repo_path, "package.json")):
        return "npm test --silent"
    return "python3 -m pytest -q"


def run_existing_repo_pipeline(repo_path: str, attempt_pr: bool = True) -> dict:
    if not os.path.isdir(repo_path):
        raise FileNotFoundError(f"Not a directory: {repo_path}")
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        return {"stage": "NOT_A_REPO", "detail": f"{repo_path} is not a git repository"}

    # Step 1 -- understand (reused, not reimplemented).
    audit_result = audit(repo_path)
    print(format_audit(audit_result))

    findings = [f for f in audit_result.get("findings", []) if f.get("severity") in ("high", "medium")]
    findings.sort(key=lambda f: {"high": 0, "medium": 1}.get(f.get("severity"), 2))
    targeted = findings[:MAX_FIXES_PER_RUN]
    if not targeted:
        return {"stage": "NO_ACTIONABLE_FINDINGS", "audit": audit_result}

    # Step 2 -- branch. Never work on the repo's current branch directly.
    orig_branch = _run("git rev-parse --abbrev-ref HEAD", repo_path)["stdout"].strip() or "main"
    branch_name = f"aura/fix-{int(time.time())}"
    checkout = _run(f"git checkout -q -b {branch_name}", repo_path)
    if checkout["exit_code"] != 0:
        return {"stage": "BRANCH_FAILED", "detail": checkout["stderr"][:300], "audit": audit_result}

    files = collect_files(repo_path)
    changes_made = {}
    explanations = []

    # Step 3 -- plan + implement, one finding at a time.
    for finding in targeted:
        context = "\n\n".join(f"--- {p} ---\n{c}" for p, c in files.items())
        user_message = (
            f"Repository files:\n\n{context}\n\n"
            f"Finding to fix:\n[{finding.get('severity')}] "
            f"{finding.get('file', '(unspecified file)')}: {finding.get('note', '')}\n\n"
            "Fix this finding now."
        )
        result = call_claude_json(system=FIX_SYSTEM_PROMPT, user_message=user_message, max_tokens=3000)
        patches = result.get("patches", {})
        for rel_path, content in patches.items():
            full_path = os.path.join(repo_path, rel_path)
            os.makedirs(os.path.dirname(full_path) or repo_path, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            files[rel_path] = content
            changes_made[rel_path] = finding.get("note", "")
        explanations.append(f"- {finding.get('note', '')}: {result.get('explanation', '')}")

    if not changes_made:
        _run(f"git checkout -q {orig_branch}", repo_path)
        _run(f"git branch -D {branch_name}", repo_path)
        return {"stage": "NO_CHANGES_PRODUCED", "audit": audit_result, "targeted_findings": targeted}

    # Step 4 -- retest. Best-effort: an arbitrary existing repo may have
    # no discoverable/runnable test suite at all -- that's a reported
    # fact (tests_passed stays False), not something to paper over.
    test_cmd = _detect_test_command(repo_path)
    test_result = _run(test_cmd, repo_path, timeout=120)
    tests_passed = test_result["exit_code"] == 0

    # Step 5 -- security re-scan, same checker the build pipeline uses.
    sec_result = security_scan({p: files[p] for p in changes_made})
    print(format_security(sec_result))

    # Step 6 -- commit on the fix branch only.
    _run("git add -A", repo_path)
    commit_msg = "AURA: automated fix\n\n" + "\n".join(explanations)
    msg_path = os.path.join(repo_path, ".aura_pr_commit_msg.tmp")
    with open(msg_path, "w", encoding="utf-8") as f:
        f.write(commit_msg)
    commit_result = _run(f"git commit -q -F {os.path.basename(msg_path)}", repo_path)
    if os.path.exists(msg_path):
        os.remove(msg_path)

    report = {
        "stage": "BRANCH_READY",
        "branch": branch_name,
        "base_branch": orig_branch,
        "audit": audit_result,
        "targeted_findings": targeted,
        "changes_made": list(changes_made.keys()),
        "test_command": test_cmd,
        "tests_passed": tests_passed,
        "test_output": (test_result["stdout"] + test_result["stderr"])[-1500:],
        "security": sec_result,
        "commit": commit_result,
    }

    # Step 7 -- gated PR. Same "don't let it ship itself" principle as
    # the Phase 8b deployment gate: both conditions must hold, and the
    # caller can also opt out of PR creation entirely via attempt_pr.
    reasons_blocked = []
    if not attempt_pr:
        reasons_blocked.append("PR creation not requested")
    if not tests_passed:
        reasons_blocked.append("tests failed")
    if sec_result.get("high_count", 0):
        reasons_blocked.append("high-severity security finding introduced")

    if not reasons_blocked:
        pr_result = _try_create_pr(repo_path, branch_name, orig_branch, commit_msg)
        report["pr"] = pr_result
        report["stage"] = "PR_CREATED" if pr_result.get("created") else "PR_NOT_CREATED"
    else:
        report["pr"] = {"created": False, "detail": "; ".join(reasons_blocked)}
        report["stage"] = "BRANCH_READY_NO_PR"

    return report


def _try_create_pr(repo_path: str, branch_name: str, base_branch: str, body: str) -> dict:
    push_result = _run(f"git push -u origin {branch_name}", repo_path, timeout=60)
    if push_result["exit_code"] != 0:
        return {"created": False, "detail": f"push failed (no remote/credentials on this machine?): {push_result['stderr'][:300]}"}

    gh_check = _run("gh --version", repo_path, timeout=10)
    if gh_check["exit_code"] != 0:
        return {"created": False, "detail": "branch pushed, but the GitHub CLI ('gh') isn't installed/authenticated here -- open the PR manually, or install+login gh and re-run"}

    body_path = os.path.join(repo_path, ".aura_pr_body.tmp")
    with open(body_path, "w", encoding="utf-8") as f:
        f.write(body)
    pr_result = _run(
        f'gh pr create --base {base_branch} --head {branch_name} '
        f'--title "AURA: automated fix" --body-file {os.path.basename(body_path)}',
        repo_path, timeout=30,
    )
    if os.path.exists(body_path):
        os.remove(body_path)
    if pr_result["exit_code"] != 0:
        return {"created": False, "detail": f"gh pr create failed: {pr_result['stderr'][:300]}"}
    return {"created": True, "detail": pr_result["stdout"].strip()}


def format_pipeline_report(report: dict) -> str:
    lines = [f"EXISTING-REPO PIPELINE: {report['stage']}"]
    if report["stage"] in ("NOT_A_REPO", "NO_ACTIONABLE_FINDINGS", "BRANCH_FAILED", "NO_CHANGES_PRODUCED"):
        if report.get("detail"):
            lines.append(f"  {report['detail']}")
        return "\n".join(lines)
    lines.append(f"  Branch        : {report.get('branch')} (base: {report.get('base_branch')})")
    lines.append(f"  Fixed         : {', '.join(report.get('changes_made', [])) or '(none)'}")
    lines.append(f"  Tests         : {'PASS' if report.get('tests_passed') else 'FAIL'} ({report.get('test_command')})")
    sec = report.get("security", {})
    lines.append(f"  Security      : {sec.get('high_count', 0)} high, {sec.get('medium_count', 0)} medium")
    pr = report.get("pr", {})
    lines.append(f"  Pull Request  : {'created -- ' if pr.get('created') else 'NOT created -- '}{pr.get('detail', '')}")
    return "\n".join(lines)
