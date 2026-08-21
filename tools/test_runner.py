"""
Test runner tool for AURA agents.
Runs pytest inside the sandbox and returns a structured result.
"""
from tools.sandbox import run_in_sandbox


def run_tests() -> dict:
    result = run_in_sandbox("python -m pytest -q --no-header", timeout=120)
    output = result["stdout"] + result["stderr"]
    passed = "failed" not in output.lower() and result["exit_code"] == 0
    return {
        "passed": passed,
        "exit_code": result["exit_code"],
        "raw_output": output.strip(),
    }