<div align="center">

# 🌌 AURA
### Autonomous Software Engineering Agent

*Give it a sentence. Get back a built, tested, reviewed project — or a fixed PR on an existing one.*

![Python](https://img.shields.io/badge/python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/server-FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![OpenRouter](https://img.shields.io/badge/LLM-OpenRouter%20(free--tier)-8A2BE2?style=flat-square)
![Docker](https://img.shields.io/badge/sandbox-Docker-2496ED?style=flat-square&logo=docker&logoColor=white)
![Status](https://img.shields.io/badge/status-active--dev-brightgreen?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-yellow?style=flat-square)

</div>

---

## ✨ What it does

AURA is a multi-agent pipeline, not a single prompt wrapper. It plans like an architect, codes like a team, tests and security-scans its own output, and knows when to stop and hand control back to a human.

It runs in two worlds:

| | |
|---|---|
| 🏗️ **Greenfield** | Turn a plain-English request into a full, tested project from nothing |
| 🔧 **Existing repos** | Audit, fix, and open a gated pull request against a real codebase — autonomously, within hard safety limits |

---

## 🚀 Usage

<table>
<tr><td><b>Build something new</b></td></tr>
<tr><td>

```bash
python main.py "Make me a Flask API with a /hello endpoint that returns JSON"
```

</td></tr>
<tr><td><b>Audit a repo — read-only, zero writes</b></td></tr>
<tr><td>

```bash
python main.py --audit /path/to/repo
```

</td></tr>
<tr><td><b>Fix a repo and open a PR</b></td></tr>
<tr><td>

```bash
python main.py --fix-repo /path/to/repo
python main.py --fix-repo --no-pr /path/to/repo   # stop after branch + commit
```

</td></tr>
<tr><td><b>Run it as a bounded autonomous loop</b></td></tr>
<tr><td>

```bash
python main.py --auto-loop /path/to/repo
python main.py --auto-loop --max-iterations 5 /path/to/repo
```

</td></tr>
<tr><td><b>Or spin up the web API</b></td></tr>
<tr><td>

```bash
python server.py
```

Submit a build → poll job status → download the finished project as a zip.

</td></tr>
</table>

---

## 🔄 The build pipeline

```
Requirements → Architect → Plan → Code (backend + frontend) → DevOps (CI)
     → DB Schema* → Write → Run → Test
          ↳ on failure: Infra-check → Debugger loop → Retest
     → Security Scan → Reviewer → Critic → Docs → Report
```
<sub>*only when the plan calls for one</sub>

The existing-repo pipeline (`--fix-repo`) reuses this same spine:

```
Audit → Plan the fix → Implement → Test → Security Scan → Review
     → Branch + Commit → Gated PR
```

And `--auto-loop` wraps that in an outer loop:

```
MONITOR → detect issue → [fix pipeline] → MONITOR → ... → healthy or capped
```

---

## 🧠 Architecture

<details>
<summary><b>30+ agents, each single-purpose, composed by an orchestrator</b></summary>
<br>

**Build agents** — `architect` · `planner` · `coder` · `frontend_coder` · `db_agent` · `devops_agent`

**Quality agents** — `debugger` · `infra_check` · `security` · `dependency_scanner` · `reviewer` · `critic` · `runtime_agent` · `performance_agent`

**Existing-repo agents** — `audit_agent` · `pr_agent` · `autonomous_loop`

**Product & docs** — `product_manager` · `requirements_agent` · `documentation_agent` · `issue_agent` · `deployment_agent`

**Infrastructure** — `release_gate` (ship/no-ship gate) · `evaluation` (scorecard) · `traceability` · `event_log` · `metrics` · `state_machine` · `failure_clustering` · `html_report` · `context_engine` · `project_memory` · `semantic_memory` · `episodic_memory`

**Sandboxing & safety** — `tools/sandbox.py` (Docker execution) · `tools/permissions.py` · `tools/git_tool.py` (branch-only commits) · `tools/filesystem.py` · `tools/terminal.py` · `tools/test_runner.py`

</details>

---

## ⚙️ Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Add your OpenRouter key:

```env
OPENROUTER_API_KEY=sk-or-...
```

AURA runs entirely on **OpenRouter's free-tier models**, with an automatic fallback chain — when one model hits its daily rate limit, it seamlessly falls through to the next. Run `python list_free_models.py` to see the current free lineup.

---

## 🛡️ Safety boundaries

- 🐳 Generated and modified code executes inside a **Docker sandbox** — never on the host
- 🌿 Existing-repo fixes always land on a fresh `aura/fix-*` branch — the default branch is **never** touched
- ✅ A PR opens only if tests pass **and** no new high-severity security finding was introduced — otherwise AURA stops at "branch ready" for human review
- 🛑 The autonomous loop has a **hard iteration cap** and halts immediately on any unresolved failure, rather than stacking changes unsupervised

---

## 📄 License

Licensed under the [MIT License](LICENSE) — free to use, modify, and distribute.

---

<div align="center">
<sub>Built by <a href="https://github.com/harsh23533-del">@harsh23533-del</a></sub>
</div>
