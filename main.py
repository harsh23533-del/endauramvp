"""
AURA MVP — entry point.

Usage:
    python main.py "Make me a Flask API with a /hello endpoint"
    python main.py --approve "..."          (prompts for release approval)
    python main.py --audit <path-to-existing-repo>       (read-only findings)
    python main.py --fix-repo <path-to-existing-repo>    (Phase 9: audit -> fix -> test -> security -> branch/commit -> PR)
    python main.py --fix-repo --no-pr <path-to-existing-repo>  (stop at branch+commit, skip PR)
"""

import sys
from dotenv import load_dotenv
from core.orchestrator import build

load_dotenv()


def main():
    if len(sys.argv) < 2:
        print('Usage: python main.py "your build request here"')
        print('       python main.py --approve "your build request here"')
        print('       python main.py --audit <path-to-existing-repo>')
        print('       python main.py --fix-repo [--no-pr] <path-to-existing-repo>')
        sys.exit(1)

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
