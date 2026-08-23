"""
AURA MVP — entry point.

Usage:
    python main.py "Make me a Flask API with a /hello endpoint"
    python main.py --approve "..."          (prompts for release approval)
    python main.py --audit <path-to-existing-repo>
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
        sys.exit(1)

    if sys.argv[1] == "--audit":
        if len(sys.argv) < 3:
            print("Usage: python main.py --audit <path-to-existing-repo>")
            sys.exit(1)
        from core.audit_agent import audit, format_audit
        result = audit(sys.argv[2])
        print(format_audit(result))
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
