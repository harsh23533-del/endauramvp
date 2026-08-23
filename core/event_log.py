"""
Event log.
Records structured build events to workspace/build-events.jsonl so
the build has a real trace, not just console output that scrolls
away (PDF section 34/41 -- observability).

PDF section 27 addition -- structured agent-to-agent messages:
log_event() gained optional fields (task_id, files_changed,
tests_passed/failed, confidence) matching the message envelope
example in section 27, instead of inventing a second, parallel
logging function. Every existing call site (stage, status, detail
only) keeps working exactly as before -- the new fields default to
None/empty and are simply omitted from the written JSON when unused.
"""
import json
import os
import time
from tools.filesystem import WORKSPACE_DIR

_LOG_FILENAME = "build-events.jsonl"


def log_event(stage: str, status: str, detail: str = "", task_id: str = None,
              files_changed: list = None, tests_passed: int = None,
              tests_failed: int = None, confidence: float = None) -> None:
    """
    stage: e.g. "requirements", "architect", "planner", "coder",
           "devops", "tester", "debugger", "security", "reviewer",
           "critic", "documentation"
    status: "completed" | "failed" | "skipped"
    detail: short human-readable note

    Optional structured fields (section 27) -- pass whichever apply;
    anything left as None/empty is omitted from the logged event
    rather than written as a misleading zero/empty value.
    """
    full_path = os.path.join(WORKSPACE_DIR, _LOG_FILENAME)
    event = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "agent": stage,
        "stage": stage,
        "status": status,
        "detail": detail,
    }
    if task_id is not None:
        event["task_id"] = task_id
    if files_changed:
        event["files_changed"] = files_changed
    if tests_passed is not None:
        event["tests_passed"] = tests_passed
    if tests_failed is not None:
        event["tests_failed"] = tests_failed
    if confidence is not None:
        event["confidence"] = confidence
    with open(full_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
