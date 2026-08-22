"""
Event log.
Records structured build events to workspace/build-events.jsonl so
the build has a real trace, not just console output that scrolls
away (PDF section 34/41 -- observability).
"""
import json
import os
import time
from tools.filesystem import WORKSPACE_DIR

_LOG_FILENAME = "build-events.jsonl"


def log_event(stage: str, status: str, detail: str = "") -> None:
    """
    stage: e.g. "requirements", "architect", "planner", "coder",
           "devops", "tester", "debugger", "security", "reviewer",
           "critic", "documentation"
    status: "completed" | "failed" | "skipped"
    detail: short human-readable note
    """
    full_path = os.path.join(WORKSPACE_DIR, _LOG_FILENAME)
    event = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stage": stage,
        "status": status,
        "detail": detail,
    }
    with open(full_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
