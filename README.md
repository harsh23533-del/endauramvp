# AURA — Autonomous Coding Agent (Phase 1)

AURA takes a plain-English build request and turns it into working, tested code — no manual scaffolding required.

```
python main.py "Make me a Flask API with a /hello endpoint that returns JSON"
```

It plans the task, writes the files, installs dependencies, runs the tests, and reports back — all in one pass.

## How it works

```
Request  →  Plan  →  Code  →  Write  →  Run  →  Test  →  Report
```

1. **Plan** — the Planner agent breaks the request into a concrete task list (files to create, commands to run)
2. **Code** — the Coder agent generates the content for each file
3. **Write** — files are saved into a sandboxed `workspace/` folder
4. **Run** — setup commands (e.g. `pip install`) are executed
5. **Test** — `pytest` runs against the generated code
6. **Report** — a summary of what was built and whether tests passed is printed

There's no debugger loop yet — if tests fail, AURA reports it rather than self-correcting. That's Phase 2.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Add your Anthropic API key to `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
python main.py "Make me a Flask API with a /hello endpoint that returns JSON"
```

Generated files land in `workspace/`. Check there after a run to see what was built.

## Project structure

```
aura-mvp/
├── main.py                  # CLI entry point
├── core/
│   ├── llm.py                # Claude API wrapper
│   ├── planner.py            # Planner agent
│   ├── coder.py               # Coder agent
│   └── orchestrator.py         # Runs the full Plan → Code → Test loop
├── tools/
│   ├── filesystem.py         # Sandboxed read/write/list file tools
│   ├── terminal.py             # Sandboxed shell command runner
│   └── test_runner.py           # pytest runner
└── workspace/                 # Generated projects land here (gitignored)
```

## Roadmap

- [ ] **Debugger agent** — feed failing test output back to the Coder agent for a self-correction loop
- [ ] Split into specialist agents (Backend, Frontend, Database, Security, Reviewer)
- [ ] Sandbox `run_command` in Docker instead of the host shell
- [ ] Git integration — auto-commit after each successful stage
