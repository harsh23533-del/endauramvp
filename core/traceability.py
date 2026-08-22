"""
Requirement traceability.
Maps each functional requirement to the task/file that (likely)
implements it, using keyword overlap between the requirement text
and each task's stated purpose -- deterministic, no extra LLM call
needed (PDF section 33: "every requirement has executable evidence").
"""
import re

_STOPWORDS = {"that", "with", "this", "shall", "should", "would", "have", "from", "into", "that's"}


def _keywords(text: str) -> set:
    words = re.findall(r"[a-zA-Z]{4,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def build_traceability(requirements_spec: dict, tasks: list, test_passed: bool) -> list:
    frs = requirements_spec.get("functional_requirements", [])
    trace = []
    for fr in frs:
        fr_keywords = _keywords(fr.get("description", ""))
        best_match = None
        best_overlap = 0
        for task in tasks:
            if task.get("type") != "create_file":
                continue
            task_keywords = _keywords(task.get("purpose", ""))
            overlap = len(fr_keywords & task_keywords)
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = task["path"]

        if best_match:
            status = "covered_tests_passed" if test_passed else "covered_tests_failed"
        else:
            status = "no_matching_task"

        trace.append({
            "requirement_id": fr.get("id"),
            "description": fr.get("description"),
            "file": best_match,
            "status": status,
        })
    return trace


def format_traceability(trace: list) -> str:
    lines = ["REQUIREMENT TRACEABILITY"]
    for t in trace:
        file_part = t["file"] or "(no file matched)"
        lines.append(f"  {t['requirement_id']}: {file_part} -- {t['status']}")
    return "\n".join(lines)
