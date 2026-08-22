"""
Orchestrator -- Phase 2.
Loop:
  Architect -> Plan -> Code -> (DB schema if needed) -> Write to disk ->
  Run commands (sandboxed) -> Run tests (sandboxed) ->
  [FAIL -> Debugger loop -> retest] ->
  Security scan -> Reviewer -> Report
"""
from core.architect import design as architect_design
from core.planner import plan
from core.coder import write_code
from core.db_agent import design_schema
from core.debugger import debug
from core.reviewer import review
from core.security import scan as security_scan
from core.evaluation import score as evaluate, format_scorecard
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

    print("--- Architect: deciding approach ---")
    architecture = architect_design(user_request)
    print(f"  stack: {architecture.get('stack')}")
    print(f"  needs_database: {architecture.get('needs_database')}")
    print(f"  notes: {architecture.get('notes')}")

    print("\n--- Planner: creating task list ---")
    task_plan = plan(user_request, architecture=architecture)
    tasks = task_plan["tasks"]
    for t in tasks:
        print(f"  - {t}")

    planned_file_count = sum(1 for t in tasks if t["type"] == "create_file")

    written_files = {}

    print("\n--- Coder: writing files ---")
    for task in tasks:
        if task["type"] == "create_file":
            print(f"  writing {task['path']} ...")
            content = write_code(
                project_goal=user_request,
                file_path=task["path"],
                purpose=task.get("purpose", ""),
                existing_files=written_files,
            )
            write_file(task["path"], content)
            written_files[task["path"]] = content

    if architecture.get("needs_database"):
        print("\n--- Database Agent: designing schema ---")
        schema = design_schema(user_request)
        write_file("schema.sql", schema)
        written_files["schema.sql"] = schema
        print("  wrote schema.sql")

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

    debug_attempts = 0
    patches_rejected = 0
    debug_log = []
    while not test_result["passed"] and debug_attempts < MAX_DEBUG_ATTEMPTS:
        debug_attempts += 1
        print(f"\n--- Debugger: attempt {debug_attempts} ---")
        try:
            diagnosis = debug(user_request, written_files, test_result["raw_output"])
        except RuntimeError as e:
            print(f"  Debugger could not produce a diagnosis: {e}")
            print("  Stopping debug loop -- see BUILD SUMMARY for current state.")
            break
        print(f"  root cause: {diagnosis.get('root_cause')}")
        patches = diagnosis.get("patches", {})

        # Snapshot before applying the patch so we can roll back if the
        # patch makes things worse than before (regression protection).
        pre_patch_files = dict(written_files)
        pre_patch_failures = test_result.get("failed_count", 0) + test_result.get("error_count", 0)

        for path, content in patches.items():
            print(f"  patching {path} ...")
            write_file(path, content)
            written_files[path] = content

        print("--- Tester: re-running pytest (sandboxed) ---")
        new_test_result = run_tests()
        new_failures = new_test_result.get("failed_count", 0) + new_test_result.get("error_count", 0)

        if not new_test_result["passed"] and new_failures > pre_patch_failures:
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
            continue

        diagnosis["rejected"] = False
        debug_log.append(diagnosis)
        test_result = new_test_result
        status = "PASSED" if test_result["passed"] else "FAILED"
        print(f"  tests: {status}")
        git_tool.commit(f"Fix: {diagnosis.get('root_cause', 'debugger patch')[:70]}")

    print("\n--- Security: scanning files ---")
    security_result = security_scan(written_files)
    print(f"  security: {'PASS' if security_result['passed'] else 'ISSUES FOUND'}")
    for finding in security_result["findings"]:
        print(f"    [{finding['file']}:{finding['line']}] {finding['issue']}")

    print("\n--- Reviewer: reviewing code ---")
    try:
        review_result = review(written_files)
        print(f"  review: {'APPROVED' if review_result.get('approved') else 'CHANGES REQUESTED'}")
        for issue in review_result.get("issues", []):
            print(f"    [{issue.get('severity')}] {issue.get('file')}: {issue.get('note')}")
    except RuntimeError as e:
        print(f"  Reviewer could not complete: {e}")
        review_result = {"approved": None, "issues": [], "error": str(e)}

    git_tool.commit("Security scan + review complete")
    checkpoint_log = git_tool.log()

    report = {
        "request": user_request,
        "architecture": architecture,
        "files_written": list(written_files.keys()),
        "planned_file_count": planned_file_count,
        "command_results": command_results,
        "test_result": test_result,
        "debug_attempts": debug_attempts,
        "patches_rejected": patches_rejected,
        "debug_log": debug_log,
        "security_result": security_result,
        "review_result": review_result,
        "checkpoint_log": checkpoint_log,
    }

    scores = evaluate(report)
    report["scores"] = scores

    print("\n=== BUILD SUMMARY ===")
    print(f"Files written : {len(written_files)}")
    print(f"Tests         : {status}")
    print(f"Debug attempts: {debug_attempts} ({patches_rejected} rejected as regressions)")
    print(f"Security      : {'PASS' if security_result['passed'] else 'ISSUES'}")
    print(f"Review        : {'APPROVED' if review_result.get('approved') else 'CHANGES REQUESTED'}")
    print("======================\n")
    print(format_scorecard(scores))
    print()
    print("=== CHECKPOINTS (workspace/ has its own git history) ===")
    print(checkpoint_log)
    print("To roll back: cd workspace, then git reset --hard <commit-hash>")
    print("==========================================================\n")

    return report