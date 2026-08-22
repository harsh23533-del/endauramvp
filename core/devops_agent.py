"""
DevOps Agent.
Generates a GitHub Actions CI workflow for the generated project so
tests run automatically on every push. Deterministic templating, no
LLM call needed -- a CI config either matches the stack or it doesn't,
there's nothing to "generate creatively" here (PDF section 20).
"""

_PYTHON_WORKFLOW = """name: CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
      - name: Run tests
        run: pytest -q
"""

_GENERIC_WORKFLOW = """name: CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Placeholder build step
        run: echo "Add build/test commands for this stack"
"""


def generate_ci_workflow(architecture: dict) -> str:
    language = (architecture or {}).get("stack", {}).get("language", "").lower()
    if language == "python":
        return _PYTHON_WORKFLOW
    return _GENERIC_WORKFLOW
