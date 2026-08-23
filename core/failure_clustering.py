"""
Failure clustering.
When the Debugger needs multiple attempts, groups them so the build
summary reads as "3 attempts, 2 distinct root causes" instead of a
flat list -- easier to see whether the debugger is converging on the
problem or flailing (PDF section 29, lite version -- no parallel
sub-debuggers, just clearer reporting on the attempts already made).
"""


def cluster_failures(debug_log: list) -> dict:
    clusters = {}
    for entry in debug_log:
        cause = entry.get("root_cause", "unknown")
        # Group by the first 40 chars as a cheap similarity signal --
        # good enough to catch the debugger repeating itself.
        key = cause[:40].lower().strip()
        if key not in clusters:
            clusters[key] = {"root_cause": cause, "attempts": 0, "rejected": 0}
        clusters[key]["attempts"] += 1
        if entry.get("rejected"):
            clusters[key]["rejected"] += 1

    return {
        "total_attempts": len(debug_log),
        "distinct_causes": len(clusters),
        "clusters": list(clusters.values()),
    }


def format_clusters(result: dict) -> str:
    if result["total_attempts"] == 0:
        return ""
    lines = [
        f"FAILURE CLUSTERS: {result['total_attempts']} attempt(s), "
        f"{result['distinct_causes']} distinct root cause(s)"
    ]
    for c in result["clusters"]:
        lines.append(f"  [{c['attempts']}x, {c['rejected']} rejected] {c['root_cause'][:80]}")
    return "\n".join(lines)
