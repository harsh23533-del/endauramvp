"""
Build state machine.
Tracks the explicit sequence of states a build moves through, so a
build's history is a clear timeline instead of just scattered print
statements (PDF section 42).

States: CREATED -> ANALYZING -> PLANNING -> ARCHITECTING -> IMPLEMENTING
        -> TESTING -> DEBUGGING (if needed) -> SECURITY_REVIEW
        -> QUALITY_REVIEW -> RELEASE_CANDIDATE -> APPROVAL -> DEPLOYED
Failure states: BLOCKED, FAILED, HUMAN_REVIEW
"""
import time


class StateMachine:
    def __init__(self):
        self.transitions = []
        self.current = None
        self.enter("CREATED")

    def enter(self, state: str, detail: str = "") -> None:
        self.current = state
        self.transitions.append({
            "state": state,
            "detail": detail,
            "timestamp": time.strftime("%H:%M:%S"),
        })

    def format_timeline(self) -> str:
        lines = ["BUILD STATE TIMELINE"]
        for t in self.transitions:
            detail = f" -- {t['detail']}" if t["detail"] else ""
            lines.append(f"  {t['timestamp']}  {t['state']}{detail}")
        return "\n".join(lines)
