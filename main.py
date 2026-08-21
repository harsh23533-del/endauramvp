"""
AURA MVP — entry point.

Usage:
    python main.py "Make me a Flask API with a /hello endpoint"
"""

import sys
from dotenv import load_dotenv
from core.orchestrator import build

load_dotenv()


def main():
    if len(sys.argv) < 2:
        print('Usage: python main.py "your build request here"')
        sys.exit(1)

    user_request = " ".join(sys.argv[1:])
    build(user_request)


if __name__ == "__main__":
    main()
