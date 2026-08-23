"""
Metrics Tracker -- Phase 7.
Records every LLM call AURA makes during a build (which model,
how long it took, how many tokens, how many retries/fallbacks it
took to get a usable response) so a build report shows not just
whether the build worked, but what it cost in time and API calls --
useful for comparing agent efficiency across runs and models.

Module-level state, reset at the start of every build() call --
AURA runs one build at a time, single-threaded, so a plain list is
enough; no need to thread a tracker instance through every agent.

Note on cost: AURA's default model chain is all ":free" OpenRouter
models, so dollar cost is always $0. What actually matters here is
token volume and latency/retries, since those are the real limiting
resources on a free tier (rate limits, daily quotas).
"""
import time

_calls = []
_next_call_id = 0


def reset():
    """Clear all recorded calls. Call once at the start of every build."""
    global _next_call_id
    _calls.clear()
    _next_call_id = 0


def new_call_id() -> int:
    """
    One id per logical call_claude()/call_claude_json() invocation --
    every attempt made while chasing that one logical call (retries on
    the same model, fallbacks to the next model) shares this id, which
    is how the summary tells a "retry" apart from a separate LLM call.
    """
    global _next_call_id
    _next_call_id += 1
    return _next_call_id


def record_attempt(call_id: int, model: str, attempt: int, latency: float,
                    success: bool, prompt_tokens: int = 0,
                    completion_tokens: int = 0, error: str = None):
    _calls.append({
        "call_id": call_id,
        "model": model,
        "attempt": attempt,
        "latency": round(latency, 3),
        "success": success,
        "prompt_tokens": prompt_tokens or 0,
        "completion_tokens": completion_tokens or 0,
        "error": error,
    })


def summary() -> dict:
    if not _calls:
        return {
            "invocations": 0, "total_attempts": 0, "retries": 0,
            "successful": 0, "failed": 0,
            "total_latency": 0.0, "avg_latency": 0.0,
            "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "by_model": {},
        }

    invocations = len({c["call_id"] for c in _calls})
    total_attempts = len(_calls)
    successful = [c for c in _calls if c["success"]]
    failed = [c for c in _calls if not c["success"]]
    total_latency = sum(c["latency"] for c in _calls)
    prompt_tokens = sum(c["prompt_tokens"] for c in _calls)
    completion_tokens = sum(c["completion_tokens"] for c in _calls)

    by_model = {}
    for c in _calls:
        m = by_model.setdefault(c["model"], {
            "attempts": 0, "successes": 0, "failures": 0,
            "latency": 0.0, "tokens": 0,
        })
        m["attempts"] += 1
        m["successes"] += 1 if c["success"] else 0
        m["failures"] += 0 if c["success"] else 1
        m["latency"] = round(m["latency"] + c["latency"], 3)
        m["tokens"] += c["prompt_tokens"] + c["completion_tokens"]

    return {
        "invocations": invocations,
        "total_attempts": total_attempts,
        "retries": total_attempts - invocations,
        "successful": len(successful),
        "failed": len(failed),
        "total_latency": round(total_latency, 2),
        "avg_latency": round(total_latency / total_attempts, 2),
        "total_tokens": prompt_tokens + completion_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "by_model": by_model,
    }


def format_metrics(m: dict) -> str:
    lines = [
        "LLM METRICS",
        f"  Invocations    : {m['invocations']} logical call(s)"
        + (f", {m['retries']} retry/fallback attempt(s)" if m["retries"] else ""),
        f"  Latency        : {m['total_latency']}s total / {m['avg_latency']}s avg per attempt",
        f"  Tokens         : {m['total_tokens']} total ({m['prompt_tokens']} prompt / {m['completion_tokens']} completion)",
        f"  Cost           : $0.00 (free-tier models only)",
    ]
    if m["by_model"]:
        lines.append("  By model:")
        for model, stats in m["by_model"].items():
            lines.append(
                f"    - {model}: {stats['attempts']} attempt(s), "
                f"{stats['successes']} ok / {stats['failures']} failed, "
                f"{stats['latency']}s, {stats['tokens']} tokens"
            )
    return "\n".join(lines)
