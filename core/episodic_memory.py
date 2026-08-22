"""
Episodic Memory (PDF section 25 - Episodic memory).
Logs past debugger failures so future debugging attempts (even in later
builds of the same project) can see "this kind of failure happened
before, here's what fixed it" instead of starting cold every time.
"""

import json
import os

EPISODES_PATH = "workspace_episodes.jsonl"


def log_episode(user_request: str, root_cause: str, fix_summary: str) -> None:
    entry = {
        "request": user_request,
        "root_cause": root_cause,
        "fix": fix_summary,
    }
    with open(EPISODES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def recent_episodes(limit: int = 5) -> list:
    if not os.path.exists(EPISODES_PATH):
        return []
    episodes = []
    with open(EPISODES_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                episodes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return episodes[-limit:]


def print_recent_episodes(limit: int = 5) -> None:
    episodes = recent_episodes(limit)
    if not episodes:
        return
    print("--- Episodic Memory: past failures on record ---")
    for ep in episodes:
        print(f"  root cause: {ep['root_cause']}")
        print(f"    fix: {ep['fix']}")
    print()
