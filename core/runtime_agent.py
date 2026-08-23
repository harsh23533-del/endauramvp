"""
Runtime Agent.
Actually starts the generated app (best-effort) and checks it comes
up without crashing -- a signal distinct from unit tests, which can
pass even if the app itself fails to boot (missing import at module
level, port binding issue, etc). PDF section 13, scaled down: no
Docker Compose / multi-service orchestration, just "does it start."
"""
from tools.sandbox import run_in_sandbox

# Best-effort: try starting a Flask app in the background, wait briefly,
# hit it, then kill it -- all inside ONE sandboxed container so the
# server and the curl call share localhost.
_HEALTH_CHECK_CMD = (
    "if [ -f app.py ]; then "
    "  (python app.py > /tmp/aura_runtime.log 2>&1 &) ; "
    "  sleep 2 ; "
    "  RESULT=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:5000/ --max-time 3 || echo 'NO_RESPONSE') ; "
    "  echo \"AURA_RUNTIME_HTTP_CODE:$RESULT\" ; "
    "  cat /tmp/aura_runtime.log ; "
    "  pkill -f 'python app.py' 2>/dev/null || true ; "
    "else "
    "  echo 'AURA_RUNTIME_SKIP:no app.py found' ; "
    "fi"
)


def check_runtime(written_files: dict) -> dict:
    if "app.py" not in written_files:
        return {"attempted": False, "started": None, "detail": "no app.py to run"}

    result = run_in_sandbox(_HEALTH_CHECK_CMD, timeout=15)
    output = result["stdout"] + result["stderr"]

    if "AURA_RUNTIME_SKIP" in output:
        return {"attempted": False, "started": None, "detail": "no app.py to run"}

    if "AURA_RUNTIME_HTTP_CODE:NO_RESPONSE" in output:
        return {"attempted": True, "started": False, "detail": "app did not respond -- likely crashed on startup", "log": output[-500:]}

    if "AURA_RUNTIME_HTTP_CODE:" in output:
        code = output.split("AURA_RUNTIME_HTTP_CODE:")[1].split()[0]
        # Any HTTP response (even 404/500) means the process booted and served a request.
        return {"attempted": True, "started": True, "detail": f"responded with HTTP {code}", "log": output[-500:]}

    return {"attempted": True, "started": None, "detail": "inconclusive", "log": output[-500:]}


def format_runtime(result: dict) -> str:
    if not result["attempted"]:
        return f"RUNTIME CHECK: skipped ({result['detail']})"
    status = "OK" if result["started"] else "FAILED"
    return f"RUNTIME CHECK: {status} -- {result['detail']}"
