"""
AURA MVP — entry point.

Usage:
    python main.py "Make me a Flask API with a /hello endpoint"
    python main.py --approve "..."          (prompts for release approval)
    python main.py --audit <path-to-existing-repo>       (read-only findings)
    python main.py --fix-repo <path-to-existing-repo>    (Phase 9: audit -> fix -> test -> security -> review -> branch/commit -> PR)
    python main.py --fix-repo --no-pr <path-to-existing-repo>  (stop at branch+commit, skip PR)
    python main.py --auto-loop <path-to-existing-repo>          (Phase 10: MONITOR -> fix pipeline -> MONITOR, until healthy or capped)
    python main.py --auto-loop --max-iterations 5 <path>        (override the default cap of 3)
"""

import sys
from dotenv import load_dotenv
from core import llm
from core.orchestrator import build

load_dotenv()


def _pop_api_key(argv: list) -> tuple[list, str | None]:
    """
    Pulls a leading/anywhere `--api-key <key>` pair out of argv so every
    subcommand below can opt to run on a caller-supplied OpenRouter key
    instead of the .env OPENROUTER_API_KEY, without each branch having
    to parse it individually.
    """
    argv = list(argv)
    if "--api-key" in argv:
        i = argv.index("--api-key")
        if i + 1 >= len(argv):
            print("Usage: --api-key <your-openrouter-key> (value missing)")
            sys.exit(1)
        key = argv[i + 1]
        del argv[i:i + 2]
        return argv, key
    return argv, None


def main():
    argv, api_key = _pop_api_key(sys.argv[1:])
    sys.argv = [sys.argv[0]] + argv

    if len(sys.argv) < 2:
        print('Usage: python main.py "your build request here"')
        print('       python main.py --approve "your build request here"')
        print('       python main.py --audit <path-to-existing-repo>')
        print('       python main.py --fix-repo [--no-pr] <path-to-existing-repo>')
        print('       python main.py --auto-loop [--max-iterations N] <path-to-existing-repo>')
        print('       Add --api-key <key> to any command to run on your own')
        print('       OpenRouter key instead of the one in .env.')
        sys.exit(1)

    with llm.use_api_key(api_key):
        _run()


def _run():
    if sys.argv[1] == "--audit":
        if len(sys.argv) < 3:
            print("Usage: python main.py --audit <path-to-existing-repo>")
            sys.exit(1)
        from core.audit_agent import audit, format_audit
        result = audit(sys.argv[2])
        print(format_audit(result))
        return

    if sys.argv[1] == "--fix-repo":
        rest = sys.argv[2:]
        attempt_pr = True
        if rest and rest[0] == "--no-pr":
            attempt_pr = False
            rest = rest[1:]
        if len(rest) < 1:
            print("Usage: python main.py --fix-repo [--no-pr] <path-to-existing-repo>")
            sys.exit(1)
        from core.pr_agent import run_existing_repo_pipeline, format_pipeline_report
        result = run_existing_repo_pipeline(rest[0], attempt_pr=attempt_pr)
        print("\n" + format_pipeline_report(result))
        return

    if sys.argv[1] == "--auto-loop":
        rest = sys.argv[2:]
        max_iterations = 3
        if rest and rest[0] == "--max-iterations":
            if len(rest) < 3:
                print("Usage: python main.py --auto-loop --max-iterations N <path-to-existing-repo>")
                sys.exit(1)
            max_iterations = int(rest[1])
            rest = rest[2:]
        if len(rest) < 1:
            print("Usage: python main.py --auto-loop [--max-iterations N] <path-to-existing-repo>")
            sys.exit(1)
        from core.autonomous_loop import run_autonomous_loop, format_loop_report
        result = run_autonomous_loop(rest[0], max_iterations=max_iterations)
        print("\n" + format_loop_report(result))
        return

    if sys.argv[1] == "--approve":
        if len(sys.argv) < 3:
            print('Usage: python main.py --approve "your build request here"')
            sys.exit(1)
        user_request = " ".join(sys.argv[2:])
        build(user_request, require_approval=True)
        return

    user_request = " ".join(sys.argv[1:])
    build(user_request)


if __name__ == "__main__":
    main()
