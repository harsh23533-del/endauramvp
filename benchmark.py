"""
AURA Evaluation Benchmark.
Runs a fixed set of standardized build tasks through the pipeline and
prints a comparison table of results (PDF section 54). Scaled down to
a handful of tasks appropriate for an MVP -- add more as the project
matures.

NOTE: each task makes many LLM calls (Requirements, Architect, Planner,
Coder per file, Debugger retries, Reviewer, Critic). Running this
consumes real API quota -- best run when you have headroom.

Usage:
    python benchmark.py
"""
from dotenv import load_dotenv
load_dotenv()

from core.orchestrator import build

TASKS = [
    "Make a Flask API with a GET /hello endpoint returning JSON",
    "Make a Flask API with a GET /add endpoint that adds two query params",
    "Make a Flask app with a homepage contact form with name and email fields",
]


def run_benchmark():
    results = []
    for i, task in enumerate(TASKS, 1):
        print(f"\n{'=' * 60}\nBENCHMARK TASK {i}/{len(TASKS)}: {task}\n{'=' * 60}")
        try:
            report = build(task)
            results.append({"task": task, "scores": report.get("scores", {}), "error": None})
        except Exception as e:
            results.append({"task": task, "scores": {}, "error": str(e)})

    print(f"\n\n{'=' * 60}\nBENCHMARK SUMMARY\n{'=' * 60}")
    print(f"{'Task':<55} {'Overall':>8}")
    for r in results:
        if r["error"]:
            overall = "ERROR"
        else:
            overall = r["scores"].get("overall", "N/A")
        print(f"{r['task'][:53]:<55} {str(overall):>8}")

    valid_scores = [r["scores"]["overall"] for r in results if r["scores"].get("overall") is not None]
    if valid_scores:
        avg = sum(valid_scores) / len(valid_scores)
        print(f"\nAverage overall score: {avg:.1f}%")


if __name__ == "__main__":
    run_benchmark()
