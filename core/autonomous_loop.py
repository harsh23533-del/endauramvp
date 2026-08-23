"""
Autonomous Engineering Loop -- Phase 10 (PDF section 52).

Wraps the Phase 9 existing-repo pipeline (audit -> plan -> implement
-> test -> security -> review -> branch/commit -> gated PR) in a
bounded loop:

    MONITOR -> DETECT ISSUE -> [Phase 9 pipeline] -> MONITOR -> ...

This is deliberately NOT reimplemented from scratch -- every step
inside one iteration is the exact Phase 9 pipeline, reused as-is.
Phase 10 only adds the outer MONITOR/loop/stop-condition wrapper
section 52 describes.

Stopping conditions (never an unbounded loop against a real repo --
section 21's "controlled autonomy", applied here):
  - MONITOR finds no actionable findings left -> system considered
    healthy, loop stops.
  - An iteration doesn't reach PR_CREATED (tests failed, high-sev
    finding, reviewer rejected, or PR skipped/failed) -> loop stops
    immediately for human review, rather than attempting another
    autonomous change on top of an unresolved one.
  - max_iterations reached -> hard safety cap, stops regardless of
    findings remaining.
"""
from core.audit_agent import audit
from core.pr_agent import run_existing_repo_pipeline, format_pipeline_report

MAX_ITERATIONS_DEFAULT = 3


def run_autonomous_loop(repo_path: str, max_iterations: int = MAX_ITERATIONS_DEFAULT, attempt_pr: bool = True) -> dict:
    iterations = []

    for i in range(1, max_iterations + 1):
        print(f"\n===== AUTONOMOUS LOOP -- iteration {i}/{max_iterations} =====")
        print("--- MONITOR: checking for actionable findings ---")

        monitor_result = audit(repo_path)
        actionable = [f for f in monitor_result.get("findings", []) if f.get("severity") in ("high", "medium")]

        if not actionable:
            print("  No actionable findings -- system considered healthy. Stopping loop.")
            iterations.append({"iteration": i, "stage": "HEALTHY", "monitor": monitor_result})
            break

        print(f"  {len(actionable)} actionable finding(s) detected -- running fix pipeline.")
        pipeline_report = run_existing_repo_pipeline(repo_path, attempt_pr=attempt_pr)
        print(format_pipeline_report(pipeline_report))
        iterations.append({"iteration": i, "stage": pipeline_report["stage"], "pipeline": pipeline_report})

        if pipeline_report["stage"] != "PR_CREATED":
            print(f"  Iteration did not reach a shippable state ({pipeline_report['stage']}) -- "
                  "stopping loop for human review rather than layering another autonomous change on top.")
            break
    else:
        print(f"\n  Reached max_iterations ({max_iterations}) -- stopping as a safety cap, "
              "not because the system is confirmed healthy.")

    final_stage = iterations[-1]["stage"] if iterations else "NO_ITERATIONS"
    return {"iterations": iterations, "final_stage": final_stage}


def format_loop_report(result: dict) -> str:
    lines = [f"AUTONOMOUS LOOP: {len(result['iterations'])} iteration(s) -- final state: {result['final_stage']}"]
    for entry in result["iterations"]:
        lines.append(f"  Iteration {entry['iteration']}: {entry['stage']}")
    return "\n".join(lines)
