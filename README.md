# AURA — Autonomous Unified Software Engineering Agent

You give AURA a plain-English build request. It plans it, writes the code,
tests it, debugs its own failures, scans it for security issues, reviews it,
and — once a human approves — deploys it. It can also point at an *existing*
repository, find real issues, fix them, and open a pull request. All of this
runs as a bounded, self-correcting loop with hard safety gates at every
step that could do real damage.

This README reflects the current state of the project — Phases 1–10 of the
original architecture doc are complete. See the audit report generated
alongside this repo for a full section-by-section comparison of what's
built vs. the original design doc, including honest gaps.

## What it actually does today

**Mode 1 — Build something new:**
```bash
python main.py "Make me a Flask API with a /hello endpoint that returns JSON"
```
Requirements → Architecture (scored, multi-candidate) → Product plan → Code
(backend + frontend + DB as needed) → Tests → Debug loop on failure →
Security scan → Code review → Adversarial critic → Release gate → (with
`--approve`) merge to main → deployment pipeline.

**Mode 2 — Fix an existing repository:**
```bash
python main.py --fix-repo <path-to-repo>          # audit -> fix -> test -> security -> review -> branch/commit -> PR
python main.py --audit <path-to-repo>             # read-only findings, no changes made
```

**Mode 3 — Autonomous loop on an existing repository:**
```bash
python main.py --auto-loop <path-to-repo>         # MONITOR -> fix pipeline -> MONITOR, until healthy or capped
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and add your OpenRouter key (AURA calls free-tier models via
OpenRouter's OpenAI-compatible API, with automatic fallback across several
models when one hits its daily rate limit):

```
OPENROUTER_API_KEY=sk-or-...
```

Optional overrides in `.env` (model router — see Architecture below):
```
OPENROUTER_MODEL=                 # force one model everywhere, skips the router
OPENROUTER_MODEL_REASONING=       # architecture / debugging / planning tasks
OPENROUTER_MODEL_CODING=          # code generation tasks
OPENROUTER_MODEL_FAST=            # classification / routing tasks
```

For existing-repo mode's PR/issue creation, install and authenticate the
GitHub CLI (`gh auth login`). Without it, AURA still does everything up
through branch + commit, and tells you so.

## Full CLI

```bash
python main.py "<build request>"                          # build a new project
python main.py --approve "<build request>"                # same, but require human approval before merging to main
python main.py --audit <path>                              # read-only findings on an existing repo
python main.py --fix-repo [--no-pr] <path>                 # audit -> fix -> test -> security -> review -> branch/commit -> (gated) PR
python main.py --auto-loop [--max-iterations N] <path>     # bounded MONITOR loop wrapping --fix-repo (default cap: 3)
```

## Agent architecture

| Agent | File | Role |
|---|---|---|
| Requirements Analyst | `core/requirements_agent.py` | Raw request to FR-/NFR-/AC- spec |
| Product Manager | `core/product_manager.py` | Spec to Epic to Story to Task |
| Architect | `core/architect.py` | Proposes 2-3 scored stack candidates, picks the highest-scoring one deterministically |
| Planner | `core/planner.py` | Task list to concrete file/command plan |
| Backend Engineer | `core/coder.py` | Writes backend code |
| Frontend Engineer | `core/frontend_coder.py` | Writes frontend code, aware of the backend's API surface |
| Database Engineer | `core/db_agent.py` | Schema design, only when the Architect flags a DB need |
| DevOps Agent | `core/devops_agent.py` | Generates the CI workflow |
| Debugger | `core/debugger.py` | Root-causes failing tests, patches, retries, with regression protection |
| Security Engineer | `core/security.py` + `core/dependency_scanner.py` | Static SAST (regex, OWASP-categorized) plus real pip-audit/npm audit |
| Code Reviewer | `core/reviewer.py` | Approves or requests changes, never writes code |
| Adversarial Critic | `core/critic.py` | Separate objective from the Reviewer: actively tries to find reasons to reject |
| Performance Agent | `core/performance_agent.py` | Static performance foot-gun checks |
| Documentation Agent | `core/documentation_agent.py` | Generates docs from actual build state, never invented |
| Issue Agent | `core/issue_agent.py` | Writes up unresolved failures (local ISSUE.md, or a real GitHub issue in existing-repo mode) |
| Pull Request Agent | `core/pr_agent.py` | Existing-repo mode: audit, plan, fix, test, security, review, branch/commit, gated PR |
| Autonomous Loop | `core/autonomous_loop.py` | Wraps the PR Agent in a bounded MONITOR to fix to MONITOR cycle |
| Deployment Agent | `core/deployment_agent.py` + `tools/deployment.py` | build_image, deploy_staging, gated deploy_production |

## Tool / safety architecture

- **Sandbox** (`tools/sandbox.py`): commands run in a throwaway Docker
  container, not the host shell. Falls back to a local sandboxed pip/pytest
  path if Docker isn't reachable.
- **Permission gateway** (`tools/permissions.py`): every command is checked
  against a hard, non-LLM blocklist (no `rm -rf /`, no `sudo`, no force-push,
  no piping a remote script into a shell, etc.) before it runs — a bad
  debugger patch or a prompt-injected file can't talk its way past this. On
  top of that sits a per-agent permission matrix (which agent role may use
  which capability — files/shell/network/deploy at all).
- **Human approval layer**: `--approve` gates merging to main;
  `deploy_production()` hard-refuses to run without explicit human approval
  regardless of any other setting.
- **Regression protection**: the orchestrator rejects any debugger patch
  that increases the number of failing tests, rather than accepting a
  "fix" that trades one bug for another.
- **Git-based recovery**: every build gets its own branch, a diff against
  main, and a checkpoint commit log — nothing lands on main without
  passing the release gate.

## Model router

`core/llm.py` routes each call by task type instead of using one model for
everything: `reasoning` (architecture, debugging, planning), `coding`
(code generation), `fast` (classification/extraction — not yet used by any
current agent, but wired and available). All three default to the same
free-tier model today since that's what OpenRouter's no-cost lineup
actually offers at meaningfully different quality — the routing mechanism
is real, model diversity is limited by the free tier, and improves as soon
as different models are set per role in `.env`.

## Context engineering

Early on, the Coder/Frontend/Debugger agents got the entire growing file
set on every single call. `core/context_engine.py` now scores existing
files by keyword overlap with the current task and only sends the relevant
subset (small/shared files are always included) — this is a lightweight
keyword-overlap heuristic, not a real AST/symbol index, but it closes the
same "don't dump the whole repo into the prompt" gap at MVP scale.

## Memory

- **Project memory** (`core/project_memory.py`) — persists architecture,
  stack, and conventions across builds of the same project.
- **Episodic memory** (`core/episodic_memory.py`) — remembers past
  failures so they're not repeated blind.
- **Semantic memory** (`core/semantic_memory.py`) — a small, curated
  cross-project best-practices checklist (input validation, password
  hashing, XSS escaping, etc.) injected into every Backend/Frontend
  prompt regardless of which stack the Architect picked.

## Evaluation & benchmark

`core/evaluation.py` produces an AURA Score (requirements coverage, tests,
security, quality breakdown) per build. `benchmark.py` runs a small fixed
set of standardized build tasks end-to-end and reports pass/fail per task —
a scaled-down version of the original design doc's proposed 20-task
benchmark suite.

## Known gaps (honest, not hidden)

- **No web UI** — everything above is CLI-only. There's no "type a request,
  click BUILD" interface yet.
- **No live/real-time dashboard** — `core/html_report.py` and
  `core/event_log.py` give a post-hoc report and a JSONL event trace, not a
  running live view of an in-progress build.
- **No task-graph parallelism** — the orchestrator runs every stage
  sequentially, even independent ones.
- **No real AST/vector code index** — `context_engine.py` is keyword-overlap,
  not a symbol index; fine at this scale, would need to change at real
  repo scale.

## Project structure

```
aura-mvp/
|-- main.py
|-- benchmark.py
|-- core/            (every agent + orchestration logic, see table above)
|-- tools/           (filesystem, terminal, sandbox, permissions, git, test runner, deployment)
|-- sandbox/         (Docker image definition for the sandbox)
`-- workspace/       (where generated projects land, gitignored)
```
