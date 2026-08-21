# AURA MVP — Phase 1

A minimal autonomous coding agent. You give it a plain-English build
request, and it:

1. **Plans** — breaks the request into a task list (files to create, commands to run)
2. **Codes** — generates each file's content
3. **Writes** — saves files into `workspace/` (a sandboxed folder)
4. **Runs** — executes any setup commands (e.g. `pip install`)
5. **Tests** — runs `pytest` against the generated code
6. **Reports** — prints a summary of what was built and whether tests passed

There is no debugger loop yet — if tests fail, AURA just tells you. Self-healing
comes in Phase 2.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Then open `.env` and paste in your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
python main.py "Make me a Flask API with a /hello endpoint that returns JSON"
```

AURA will create files inside `workspace/`, install dependencies, and run tests.
Check `workspace/` afterward to see the generated project.

## Project structure

```
aura-mvp/
├── main.py              # CLI entry point
├── core/
│   ├── llm.py            # Claude API wrapper
│   ├── planner.py         # Planner agent
│   ├── coder.py            # Coder agent
│   └── orchestrator.py      # Runs the full Plan -> Code -> Test loop
├── tools/
│   ├── filesystem.py     # Sandboxed read/write/list file tools
│   ├── terminal.py         # Sandboxed shell command runner
│   └── test_runner.py       # pytest runner
└── workspace/            # Where generated projects land (gitignored)
```

## Next steps (Phase 2+)

- Add a **Debugger agent**: on test failure, feed the stack trace back to the
  Coder agent and retry (self-correction loop).
- Split into more specialist agents (Backend, Frontend, Database, Security, Reviewer).
- Move `run_command` into a Docker container instead of the host shell.
- Add Git integration (auto-commit after each successful stage).
