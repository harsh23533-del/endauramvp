"""
Project Memory (PDF section 25 - Project memory).
Persists architecture, stack, and conventions to a JSON file next to the
workspace so the next build for the same project can reuse decisions
instead of re-deciding the stack from scratch every single run.
"""

import json
import os

MEMORY_PATH = "workspace_memory.json"


def load_memory() -> dict:
    if not os.path.exists(MEMORY_PATH):
        return {"architecture": None, "stack": None, "conventions": [], "past_requests": []}
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"architecture": None, "stack": None, "conventions": [], "past_requests": []}


def save_memory(user_request: str, architecture: dict) -> None:
    memory = load_memory()
    memory["architecture"] = architecture
    memory["stack"] = architecture.get("stack") if isinstance(architecture, dict) else None
    memory.setdefault("past_requests", [])
    memory["past_requests"].append(user_request)
    memory["past_requests"] = memory["past_requests"][-10:]  # keep last 10 only
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2)


def print_memory_context(memory: dict) -> None:
    if memory.get("stack"):
        print("--- Project Memory: reusing prior context ---")
        print(f"  last known stack: {memory['stack']}")
        if memory.get("past_requests"):
            print(f"  past requests this project: {len(memory['past_requests'])}")
        print()
