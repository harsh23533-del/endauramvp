"""
Infrastructure error detector.

Some test failures aren't bugs in the generated code at all -- they're
environment problems (Docker not running, network unreachable, disk
full). Handing these to the Debugger wastes attempts and produces
confident-sounding but wrong "fixes" (patching pytest.ini to work
around a Docker daemon that's simply not running, for example).

This runs BEFORE the debugger loop so AURA can tell the difference
and stop immediately with a clear, actionable message instead of
burning debug attempts on something no code patch can fix.
"""
import re

# Each pattern maps to a short, human-actionable explanation.
_INFRA_PATTERNS = [
    (re.compile(r"cannot connect to the docker daemon", re.I),
     "Docker daemon isn't running."),
    (re.compile(r"docker daemon.*(not running|is not running)", re.I),
     "Docker daemon isn't running."),
    (re.compile(r"npipe|dockerdesktoplinuxengine", re.I),
     "Docker Desktop isn't running (Windows named pipe unreachable)."),
    (re.compile(r"failed to connect to the docker api", re.I),
     "Docker Desktop isn't running or isn't ready yet."),
    (re.compile(r"connection refused", re.I),
     "A required service refused the connection (check it's running)."),
    (re.compile(r"network is unreachable|temporary failure in name resolution", re.I),
     "No network access from the sandbox -- check your internet connection."),
    (re.compile(r"no space left on device", re.I),
     "The disk is full."),
]


def detect(raw_output: str) -> str | None:
    """
    Returns a short human-readable reason if raw_output looks like an
    infrastructure/environment failure rather than a code bug.
    Returns None if it looks like an ordinary test failure.
    """
    for pattern, reason in _INFRA_PATTERNS:
        if pattern.search(raw_output):
            return reason
    return None
