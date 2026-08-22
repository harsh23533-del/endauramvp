"""
Orchestrator -- Phase 3.
Loop:
  Requirements -> Architect -> Plan -> Code (backend/frontend split) ->
  DevOps (CI) -> (DB schema if needed) -> Write to disk ->
  Run commands (sandboxed) -> Run tests (sandboxed) ->
  [FAIL -> infra-check -> Debugger loop w/ regression protection -> retest] ->
  Security scan -> Reviewer -> Critic -> Documentation -> Report
"""
from core.architect import design as architect_design
from core.planner import plan
from core.coder import write_backend_code
from core.frontend_coder import write_frontend_code
from core.file_router import classify as classify_file
from core.db_agent import design_schema
from core.debugger import debug
from core.infra_check import detect as detect_infra_error
from core.reviewer import review
from core.critic import critique
from core.security import scan as security_scan
from core.evaluation import score as evaluate, format_scorecard
from core.documentation_agent import generate_readme
from core.devops_agent import generate_ci_workflow
from core.event_log import log_event
from tools.filesystem import write_file, reset_workspace
from tools.sandbox import run_in_sandbox
from tools.test_runner import run_tests
from tools import git_tool

MAX_DEBUG_ATTEMPTS = 3


def build(user_request: str) -> dict:
    print(f"\n=== AURA: received request ===\n{user_request}\n")
    print("Resetting workspace (starting from a clean slate)...")
    reset_workspace()
    git_tool.ensure_repo()

    from core.requirements_agent import analyze_requirements, print_requirements, format_spec
    requirements_spec = analyze_requirements(user_request)
    print_requirements(requirements_spec)
    write_file("requirements.md", format_spec(requirements_spec))
    fr_count = len(requirements_spec.get("functional_requirements", []))
    log_event("requirements", "completed", f"{fr_count} functional requirements")

    architecture = architect_design(user_request)
    print(f"  stack: {architecture.get('stack')}")
    print(f"  needs_database: {architecture.get('needs_database')}")
    print(f"  notes: {architecture.get('notes')}")
    log_event("architect", "completed", str(architecture.get("stack")))

    print("\n--- Planner: creating task list ---")
    task_plan = plan(user_request, architecture=architecture, requirements=requirements_spec)
    tasks = task_plan["tasks"]
    for t in tasks:
        print(f"  - {t}")
    log_event("planner", "completed", f"{len(tasks)} tasks")

    planned_file_count = sum(1 for t in tasks if t["type"] == "create_file")

    written_files = {}

    print("\n--- Coder: writing files ---")
    for task in tasks:
        if task["type"] == "create_file":
            role = classify_file(task["path"])
            print(f"  writing {task['path']} ... ({role})")
            write_fn = write_frontend_code if role == "frontend" else write_backend_code
            content = write_fn(
                project_goal=user_request,
                file_path=task["path"],
                purpose=task.get("purpose", ""),
                existing_files=written_files,
            )
            write_file(task["path"], content)
            written_files[task["path"]] = content
    log_event("coder", "completed", f"{len(written_files)} files written")

    if architecture.get("needs_database"):
        print("\n--- Database Agent: designing schema ---")
        schema = design_schema(user_request)
        write_file("schema.sql", schema)
        written_files["schema.sql"] = schema
        print("  wrote schema.sql")
        log_event("database", "completed", "schema.sql written")

    print("\n--- DevOps Agent: generating CI workflow ---")
    ci_workflow = generate_ci_workflow(architecture)
    write_file(".github/workflows/ci.yml", ci_workflow)
    print("  wrote .github/workflows/ci.yml")
    log_event("devops", "completed", "ci.yml written")

    git_tool.commit("Initial implementation")

    print("\n--- Runner: executing setup commands (sandboxed) ---")
    command_results = []
    for task in tasks:
        if task["type"] == "run_command":
            # Skip pip install here -- the test runner installs
            # requirements.txt itself inside the SAME container that
            # runs pytest, since each sandbox run is a fresh throwaway
            # container and installed packages wouldn't carry over.
            if "pip install" in task["command"] and "requirements.txt" in task["command"]:
                print(f"  skipping (handled by test runner): {task['command']}")
                continue
            print(f"  running: {task['command']}")
            result = run_in_sandbox(task["command"])
            command_results.append(result)
            if result["exit_code"] != 0:
                print(f"    WARNING: exit code {result['exit_code']}")
                print(f"    stderr: {result['stderr'][:300]}")

    print("\n--- Tester: installing deps + running pytest (sandboxed) ---")
    test_result = run_tests()
    status = "PASSED" if test_result["passed"] else "FAILED"
    print(f"  tests: {status}")
    print(f"  {test_result['raw_output'][:800]}")
    log_event("tester", "completed" if test_result["passed"] else "failed", status)

    debug_attempts = 0
    patches_rejected = 0
    debug_log = []
    infra_error = None

    if not test_result["passed"]:
        infra_error = detect_infra_error(test_result["raw_output"])
        if infra_error:
            print(f"\n--- INFRASTRUCTURE ISSUE DETECTED (not a code bug) ---")
            print(f"  {infra_error}")
            print("  Skipping the Debugger -- no code patch can fix this.")
            print("  Fix your environment and re-run the build.")
            log_event("debugger", "skipped", f"infra issue: {infra_error}")

    while not test_result["passed"] and not infra_error and debug_attempts < MAX_DEBUG_ATTEMPTS:
        debug_attempts += 1
        print(f"\n--- Debugger: attempt {debug_attempts} ---")
        try:
            diagnosis = debug(user_request, written_files, test_result["raw_output"])
        except RuntimeError as e:
            print(f"  Debugger could not produce a diagnosis: {e}")
            print("  Stopping debug loop -- see BUILD SUMMARY for current state.")
            log_event("debugger", "failed", str(e)[:150])
            break
        print(f"  root cause: {diagnosis.get('root_cause')}")
        patches = diagnosis.get("patches", {})

        # Snapshot before applying the patch so we can roll back if the
        # patch makes things worse than before (regression protection).
        pre_patch_files = dict(written_files)
        pre_patch_failures = test_result.get("failed_count", 0) + test_result.get("error_count", 0)
        pre_patch_total = pre_patch_failures + test_result.get("passed_count", 0)

        for path, content in patches.items():
            print(f"  patching {path} ...")
            write_file(path, content)
            written_files[path] = content

        print("--- Tester: re-running pytest (sandboxed) ---")
        new_test_result = run_tests()
        new_failures = new_test_result.get("failed_count", 0) + new_test_result.get("error_count", 0)

        # Only treat this as a regression if we have a REAL baseline to
        # compare against. If pytest never even ran before (a collection
        # error like "No module named pytest" -- 0 passed AND 0 failed,
        # not because everything passed but because nothing could run),
        # there's nothing valid to protect: any outcome is progress.
        has_valid_baseline = pre_patch_total > 0

        if has_valid_baseline and not new_test_result["passed"] and new_failures > pre_patch_failures:
            print(f"  REGRESSION: failures went from {pre_patch_failures} to {new_failures} -- rejecting patch")
            # Revert files on disk to the pre-patch snapshot.
            for path, content in pre_patch_files.items():
                write_file(path, content)
            written_files.clear()
            written_files.update(pre_patch_files)
            diagnosis["rejected"] = True
            diagnosis["rejection_reason"] = f"regression: failures {pre_patch_failures} -> {new_failures}"
            debug_log.append(diagnosis)
            patches_rejected += 1
            print("  tests: FAILED (patch rejected, reverted to previous state)")
            log_event("debugger", "failed", "patch rejected (regression)")
            continue

        diagnosis["rejected"] = False
        debug_log.append(diagnosis)
        test_result = new_test_result
        status = "PASSED" if test_result["passed"] else "FAILED"
        print(f"  tests: {status}")
        log_event("debugger", "completed", diagnosis.get("root_cause", "")[:150])
        git_tool.commit(f"Fix: {diagnosis.get('root_cause', 'debugger patch')[:70]}")

    print("\n--- Security: scanning files ---")
    security_result = security_scan(written_files)
    print(f"  security: {'PASS' if security_result['passed'] else 'ISSUES FOUND'}")
    for finding in security_result["findings"]:
        print(f"    [{finding['file']}:{finding['line']}] {finding['issue']}")
    log_event("security", "completed", "PASS" if security_result["passed"] else f"{len(security_result['findings'])} issues")

    print("\n--- Reviewer: reviewing code ---")
    try:
        review_result = review(written_files)
        print(f"  review: {'APPROVED' if review_result.get('approved') else 'CHANGES REQUESTED'}")
        for issue in review_result.get("issues", []):
            print(f"    [{issue.get('severity')}] {issue.get('file')}: {issue.get('note')}")
        log_event("reviewer", "completed", "APPROVED" if review_result.get("approved") else "CHANGES REQUESTED")
    except RuntimeError as e:
        print(f"  Reviewer could not complete: {e}")
        review_result = {"approved": None, "issues": [], "error": str(e)}
        log_event("reviewer", "failed", str(e)[:150])

    print("\n--- Critic: looking for ways this breaks ---")
    try:
        critic_result = critique(written_files)
        print(f"  verdict: {critic_result.get('verdict')}")
        for b in critic_result.get("breaks_found", []):
            print(f"    [{b.get('file')}] {b.get('scenario')} -> {b.get('consequence')}")
        log_event("critic", "completed", critic_result.get("verdict", "unknown"))
    except RuntimeError as e:
        print(f"  Critic could not complete: {e}")
        critic_result = {"breaks_found": [], "verdict": "unknown", "error": str(e)}
        log_event("critic", "failed", str(e)[:150])

    report = {
        "request": user_request,
        "requirements_spec": requirements_spec,
        "architecture": architecture,
        "files_written": list(written_files.keys()),
        "planned_file_count": planned_file_count,
        "command_results": command_results,
        "test_result": test_result,
        "debug_attempts": debug_attempts,
        "patches_rejected": patches_rejected,
        "debug_log": debug_log,
        "infra_error": infra_error,
        "security_result": security_result,
        "review_result": review_result,
        "critic_result": critic_result,
    }

    scores = evaluate(report)
    report["scores"] = scores

    print("\n--- Documentation Agent: generating README ---")
    readme_content = generate_readme(report)
    write_file("README.md", readme_content)
    print("  wrote README.md")
    log_event("documentation", "completed", "README.md written")

    git_tool.commit("Security scan + review + critic complete + documentation")
    checkpoint_log = git_tool.log()
    report["checkpoint_log"] = checkpoint_log

    print("\n=== BUILD SUMMARY ===")
    print(f"Files written : {len(written_files)}")
    print(f"Tests         : {status}")
    if infra_error:
        print(f"Infra issue   : {infra_error} (fix your environment, then re-run)")
    print(f"Debug attempts: {debug_attempts} ({patches_rejected} rejected as regressions)")
    print(f"Security      : {'PASS' if security_result['passed'] else 'ISSUES'}")
    print(f"Review        : {'APPROVED' if review_result.get('approved') else 'CHANGES REQUESTED'}")
    print(f"Critic        : {critic_result.get('verdict', 'unknown')}")
    print("======================\n")
    print(format_scorecard(scores))
    print()
    print("=== CHECKPOINTS (workspace/ has its own git history) ===")
    print(checkpoint_log)
    print("To roll back: cd workspace, then git reset --hard <commit-hash>")
    print("==========================================================\n")
    print("Full event trace: workspace/build-events.jsonl")

    return report
