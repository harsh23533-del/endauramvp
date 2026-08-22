"""
Test runner tool for AURA agents.

Installs requirements and runs pytest inside a SINGLE sandbox container
run. This matters because each run_in_sandbox() call spins up a fresh
throwaway container (--rm) -- packages installed in one container do
not carry over to the next. Combining install + test into one call
keeps them in the same container.

Also parses pytest's summary line so the orchestrator can compare
pass/fail counts across runs and catch regressions (a patch that
fixes one thing but breaks another).
"""
import re
from tools.sandbox import run_in_sandbox

INSTALL_AND_TEST_CMD = (
    "if [ -f requirements.txt ]; then "
    "pip install --quiet --disable-pip-version-check -r requirements.txt; "
    "fi && python -m pytest -q --no-header"
)

# Individual patterns matched independently so order in the pytest
# summary line doesn't matter (e.g. "2 failed, 1 passed" vs
# "1 passed, 2 failed").
_PASSED_RE = re.compile(r"(\d+)\s+passed")
_FAILED_RE = re.compile(r"(\d+)\s+failed")
_ERROR_RE = re.compile(r"(\d+)\s+error")


def _parse_counts(output: str) -> dict:
    """
    Look at the last few lines of pytest output for the summary line
    and extract passed/failed/error counts. Defaults to zeros if no
    recognizable summary is found (e.g. install failed before pytest ran).
    """
    tail_lines = output.strip().splitlines()[-5:]
    for line in reversed(tail_lines):
        if "passed" in line or "failed" in line or "error" in line:
            passed_match = _PASSED_RE.search(line)
            failed_match = _FAILED_RE.search(line)
            error_match = _ERROR_RE.search(line)
            if passed_match or failed_match or error_match:
                return {
                    "passed_count": int(passed_match.group(1)) if passed_match else 0,
                    "failed_count": int(failed_match.group(1)) if failed_match else 0,
                    "error_count": int(error_match.group(1)) if error_match else 0,
                }
    return {"passed_count": 0, "failed_count": 0, "error_count": 0}


def run_tests() -> dict:
    result = run_in_sandbox(INSTALL_AND_TEST_CMD, timeout=180)
    output = result["stdout"] + result["stderr"]
    passed = "failed" not in output.lower() and result["exit_code"] == 0
    counts = _parse_counts(output)
    return {
        "passed": passed,
        "exit_code": result["exit_code"],
        "raw_output": output.strip(),
        **counts,
    }
