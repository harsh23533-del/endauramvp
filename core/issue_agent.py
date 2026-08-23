"""
Issue agent.
When the Debugger exhausts its attempts and the code is still broken
(not an infra problem -- an actual unsolved bug), writes an ISSUE.md
in the style of a GitHub issue instead of silently giving up. Mirrors
PDF section 47's "TEST FAILURE -> ISSUE GENERATOR -> GitHub Issue",
scoped down to a local markdown file (no GitHub API token needed).
"""


def generate_issue_md(user_request: str, debug_log: list, test_result: dict) -> str:
    lines = [
        "# Unresolved test failure",
        "",
        f"**Original request:** {user_request}",
        "",
        f"**Status:** Tests still failing after {len(debug_log)} debugger attempt(s).",
        "",
        "## Attempts tried",
        "",
    ]
    for i, entry in enumerate(debug_log, 1):
        rejected = entry.get("rejected", False)
        outcome = "rejected (caused a regression)" if rejected else "applied, did not fully fix it"
        lines.append(f"{i}. **{entry.get('root_cause', 'unknown cause')}** -- {outcome}")

    lines.append("")
    lines.append("## Last test output")
    lines.append("")
    lines.append("```")
    lines.append(test_result.get("raw_output", "")[-1500:])
    lines.append("```")
    lines.append("")
    lines.append("_This file was generated automatically. A human should take it from here._")

    return "\n".join(lines)
