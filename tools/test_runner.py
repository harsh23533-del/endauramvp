"""
Test runner tool for AURA agents.

Installs requirements and runs pytest inside a SINGLE sandbox container
run. This matters because each run_in_sandbox() call spins up a fresh
throwaway container (--rm) -- packages installed in one container do
not carry over to the next. Combining install + test into one call
keeps them in the same container.
"""
from tools.sandbox import run_in_sandbox

INSTALL_AND_TEST_CMD = (
    "if [ -f requirements.txt ]; then "
    "pip install --quiet --disable-pip-version-check -r requirements.txt; "
    "fi && python -m pytest -q --no-header"
)


def run_tests() -> dict:
    result = run_in_sandbox(INSTALL_AND_TEST_CMD, timeout=180)
    output = result["stdout"] + result["stderr"]
    passed = "failed" not in output.lower() and result["exit_code"] == 0
    return {
        "passed": passed,
        "exit_code": result["exit_code"],
        "raw_output": output.strip(),
    }