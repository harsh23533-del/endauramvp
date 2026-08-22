"""
Observability -- event bus.
Every meaningful thing AURA does gets emitted as a structured event:
printed live (existing prints stay untouched) AND appended to
workspace/aura_events.jsonl, so a build can be inspected after the
fact, diffed across runs, or later streamed to a UI (PDF section 34/41).

Deliberately dumb and dependency-free: a list in memory + a JSONL file.
No event bus library, no queue -- this is an MVP.
"""
import json
import os
import time
from tools.filesystem import WORKSPACE_DIR

EVENTS_FILE = "aura_events.jsonl"

# Canonical event type names (PDF section 41). Using constants instead of
# free-text strings keeps downstream consumers (a UI, a log grep) reliable.
TASK_CREATED = "TASK_CREATED"
AGENT_STARTED = "AGENT_STARTED"
AGENT_FINISHED = "AGENT_FINISHED"
FILE_WRITTEN = "FILE_WRITTEN"
COMMAND_BLOCKED = "COMMAND_BLOCKED"
TEST_STARTED = "TEST_STARTED"
TEST_FAILED = "TEST_FAILED"
TEST_PASSED = "TEST_PASSED"
BUG_DETECTED = "BUG_DETECTED"
PATCH_APPLIED = "PATCH_APPLIED"
PATCH_REJECTED = "PATCH_REJECTED"
SECURITY_SCAN_COMPLETED = "SECURITY_SCAN_COMPLETED"
REVIEW_COMPLETED = "REVIEW_COMPLETED"
CRITIC_COMPLETED = "CRITIC_COMPLETED"
BUILD_COMPLETED = "BUILD_COMPLETED"

_events = []


def _events_path() -> str:
    return os.path.join(WORKSPACE_DIR, EVENTS_FILE)


def reset() -> None:
    """Call at the start of a build so events don't leak across runs."""
    _events.clear()
    path = _events_path()
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def emit(event_type: str, **data) -> dict:
    """
    Record one event. Never raises -- observability must not be able
    to break a build, so file-write failures are swallowed.
    """
    event = {"ts": time.time(), "type": event_type, **data}
    _events.append(event)
    try:
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
        with open(_events_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        pass
    return event


def timeline() -> list:
    return list(_events)


def format_timeline() -> str:
    """Human-readable version for the console (PDF section 35)."""
    lines = []
    for e in _events:
        t = time.strftime("%H:%M:%S", time.localtime(e["ts"]))
        detail = {k: v for k, v in e.items() if k not in ("ts", "type")}
        detail_str = f" -- {detail}" if detail else ""
        lines.append(f"{t}  {e['type']}{detail_str}")
    return "\n".join(lines)
