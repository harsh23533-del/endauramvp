"""
Web wrapper around AURA's core.orchestrator.build().

AURA's core is a CLI tool built around ONE shared workspace/ directory
that gets wiped (reset_workspace()) at the start of every build. That
means this service can only ever run one build at a time, globally --
so requests are queued onto a single background worker rather than
handled concurrently. That's a deliberate constraint, not a bug: it
also protects the OpenRouter free-tier daily quota from being burned
by parallel requests.

Endpoints:
  GET  /                       simple HTML form (submit + poll + download)
  POST /api/build              {"request": "..."} -> {"job_id": "..."}
  GET  /api/jobs/{job_id}      status + log tail + report once done
  GET  /api/jobs/{job_id}/download   zip of the generated project

Auth: every /api/* call requires header  X-Access-Code: <ACCESS_CODE>
Rate limit: per-IP, ACCESS_CODE-independent, see RateLimiter below.
"""
import io
import json
import os
import queue
import secrets
import shutil
import threading
import time
import uuid
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

from core.orchestrator import build  # noqa: E402  (after load_dotenv)
from tools.filesystem import WORKSPACE_DIR  # noqa: E402

# ---------------------------------------------------------------- config --

ACCESS_CODE = os.environ.get("ACCESS_CODE")
if not ACCESS_CODE:
    ACCESS_CODE = secrets.token_urlsafe(12)
    print("=" * 60)
    print("No ACCESS_CODE set -- generated one for this run:")
    print(f"  ACCESS_CODE={ACCESS_CODE}")
    print("Set ACCESS_CODE as an env var to pin it across restarts.")
    print("=" * 60)

RATE_LIMIT_MAX = int(os.environ.get("RATE_LIMIT_MAX", "5"))       # requests
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "3600"))  # seconds
MAX_REQUEST_CHARS = 2000
BUILDS_DIR = Path(__file__).parent / "builds"
BUILDS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="AURA MVP")

# ------------------------------------------------------------ rate limit --


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window_seconds]
            if len(hits) >= self.max_requests:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True


rate_limiter = RateLimiter(RATE_LIMIT_MAX, RATE_LIMIT_WINDOW)

# --------------------------------------------------------------- job queue --

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
work_queue: "queue.Queue[str]" = queue.Queue()


def _worker():
    while True:
        job_id = work_queue.get()
        with jobs_lock:
            job = jobs[job_id]
            job["status"] = "running"
        log_buffer = io.StringIO()
        try:
            with redirect_stdout(log_buffer):
                report = build(job["request"])
            # Snapshot the event trace before archiving/returning to the
            # loop -- the NEXT queued build's reset_workspace() would wipe
            # build-events.jsonl, and this is the last safe moment to read it.
            events_snapshot = _read_workspace_events()
            archive_path = _archive_workspace(job_id)
            with jobs_lock:
                job["status"] = "done"
                job["report"] = _slim_report(report)
                job["archive"] = archive_path
                job["events"] = events_snapshot
        except Exception as e:  # noqa: BLE001 -- surface any failure to the caller
            with jobs_lock:
                job["status"] = "error"
                job["error"] = str(e)
                job["events"] = _read_workspace_events()
        finally:
            with jobs_lock:
                job["log"] = log_buffer.getvalue()[-20000:]  # cap stored log size
            work_queue.task_done()


threading.Thread(target=_worker, daemon=True).start()


def _read_workspace_events() -> list[dict]:
    """
    Parse workspace/build-events.jsonl (written live by core.event_log.log_event
    on every agent stage transition) into a list of {stage, status, detail, ...}
    dicts, in order. Missing/partial file (build hasn't started writing yet,
    or is mid-write) is handled gracefully -- this is read while a build may
    still be actively appending to it.
    """
    path = os.path.join(WORKSPACE_DIR, "build-events.jsonl")
    events = []
    if not os.path.exists(path):
        return events
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # last line may be mid-write; skip it, next poll will have it complete
    except OSError:
        pass
    return events


def _archive_workspace(job_id: str) -> str:
    """Zip workspace/ into builds/<job_id>.zip before the next build wipes it."""
    dest = BUILDS_DIR / f"{job_id}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in Path(WORKSPACE_DIR).rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                zf.write(path, path.relative_to(WORKSPACE_DIR))
    return str(dest)


def _slim_report(report: dict) -> dict:
    """Trim the full report down to what's worth showing over the API."""
    return {
        "files_written": report.get("files_written"),
        "tests_passed": (report.get("test_result") or {}).get("passed"),
        "security_passed": (report.get("security_result") or {}).get("passed"),
        "release_gate": (report.get("release_gate") or {}).get("status"),
        "deployment_stage": (report.get("deployment") or {}).get("stage"),
        "git_merged": report.get("git_merged"),
        "debug_attempts": report.get("debug_attempts"),
    }


# ----------------------------------------------------------------- auth ---


def _client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else request.client.host) or "unknown"


def _require_access(x_access_code: str | None):
    if not x_access_code or not secrets.compare_digest(x_access_code, ACCESS_CODE):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Access-Code header.")


# --------------------------------------------------------------- models ---


class BuildRequest(BaseModel):
    request: str = Field(..., min_length=1, max_length=MAX_REQUEST_CHARS)


# -------------------------------------------------------------- routes ---


@app.post("/api/build")
def start_build(body: BuildRequest, request: Request, x_access_code: str | None = Header(default=None)):
    _require_access(x_access_code)
    if not rate_limiter.check(_client_key(request)):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {RATE_LIMIT_MAX} builds per {RATE_LIMIT_WINDOW // 60} minutes.",
        )
    job_id = uuid.uuid4().hex[:12]
    with jobs_lock:
        jobs[job_id] = {"status": "queued", "request": body.request, "log": "", "created": time.time()}
    work_queue.put(job_id)
    return {"job_id": job_id, "status": "queued", "queue_position": work_queue.qsize()}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, x_access_code: str | None = Header(default=None)):
    _require_access(x_access_code)
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Unknown job id.")
        return {
            "job_id": job_id,
            "status": job["status"],
            "log_tail": job.get("log", "")[-4000:],
            "report": job.get("report"),
            "error": job.get("error"),
            "download_available": job["status"] == "done",
        }


@app.get("/api/jobs/{job_id}/events")
def job_events(job_id: str, x_access_code: str | None = Header(default=None)):
    """
    The agent-pipeline trace for this job: one entry per stage transition
    (requirements -> architect -> planner -> coder -> ... -> documentation),
    used by the frontend to animate a step-by-step pipeline view. While the
    job is still running this reads the live file directly (safe: only one
    build ever runs at a time); once done/errored it returns the snapshot
    captured right as the build finished, before the workspace could be reused.
    """
    _require_access(x_access_code)
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Unknown job id.")
        status = job["status"]
        snapshot = job.get("events")
    if status in ("done", "error") and snapshot is not None:
        return {"events": snapshot, "live": False}
    return {"events": _read_workspace_events(), "live": True}


@app.get("/api/jobs/{job_id}/file")
def job_file(job_id: str, path: str, x_access_code: str | None = Header(default=None)):
    """
    Returns the current on-disk content of one generated file, so the
    frontend can show real code as it's written (not a simulation) --
    read directly from the live workspace while the job is running, from
    the completed job's report once it's done. Path is confined to the
    workspace directory, same as tools/filesystem.py's own guard.
    """
    _require_access(x_access_code)
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Unknown job id.")
    full_path = os.path.abspath(os.path.join(WORKSPACE_DIR, path))
    if not full_path.startswith(os.path.abspath(WORKSPACE_DIR)):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if job["status"] in ("done", "error"):
        # Workspace may already be reused by a later build -- fall back to
        # the archived zip for this job instead.
        archive = job.get("archive")
        if archive and os.path.exists(archive):
            try:
                with zipfile.ZipFile(archive) as zf:
                    with zf.open(path.replace("\\", "/")) as f:
                        return {"path": path, "content": f.read().decode("utf-8", errors="replace")}
            except KeyError:
                raise HTTPException(status_code=404, detail="File not found in archive.")
        raise HTTPException(status_code=404, detail="Job finished and no archive is available.")
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not written yet.")
    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        return {"path": path, "content": f.read()}


@app.get("/api/jobs/{job_id}/download")
def job_download(job_id: str, x_access_code: str | None = Header(default=None)):
    _require_access(x_access_code)
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job.get("status") != "done" or not job.get("archive"):
            raise HTTPException(status_code=404, detail="No completed build with a downloadable archive for this id.")
        archive_path = job["archive"]
    return StreamingResponse(
        open(archive_path, "rb"),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="aura-build-{job_id}.zip"'},
    )


@app.get("/health")
def health():
    return {"ok": True, "queue_depth": work_queue.qsize()}


@app.get("/", response_class=HTMLResponse)
def index():
    return _INDEX_HTML


_INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>AURA</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    background: linear-gradient(180deg, #f6f7fb 0%, #eef1fb 40%, #f7f4fb 100%);
    color: #1c2030;
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
  }

  .hero { position: relative; height: 320vh; }
  .hero-pin { position: sticky; top: 0; height: 100vh; overflow: hidden; }
  #hero-canvas { position: absolute; inset: 0; display: block; }
  .scene {
    position: absolute; left: 50%; top: 50%;
    transform: translate(-50%, -50%);
    text-align: center; width: min(560px, 88vw);
    opacity: 0; transition: opacity 0.5s ease;
    pointer-events: none;
  }
  .scene.visible { opacity: 1; pointer-events: auto; }
  .scene .eyebrow {
    font-size: 12.5px; letter-spacing: 2px; text-transform: uppercase;
    color: #7c5cff; font-weight: 600; margin: 0 0 10px;
  }
  .scene h2 {
    font-size: clamp(28px, 5vw, 46px); margin: 0 0 12px; font-weight: 700;
    color: #14172a; letter-spacing: -0.5px;
  }
  .scene p { font-size: 16px; color: #565d75; margin: 0; line-height: 1.55; }
  .scene .cta {
    margin-top: 26px; padding: 15px 30px; font-size: 15px; font-weight: 600;
    color: #fff; border: none; border-radius: 999px; cursor: pointer;
    background: linear-gradient(135deg, #7c5cff, #5b8dff);
    box-shadow: 0 14px 30px -8px rgba(124,92,255,0.55);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }
  .scene .cta:hover { transform: translateY(-2px) scale(1.02); box-shadow: 0 18px 36px -8px rgba(124,92,255,0.65); }

  .scroll-hint {
    position: absolute; bottom: 34px; left: 50%; transform: translateX(-50%);
    font-size: 12px; color: #8891ab; letter-spacing: 1px; text-transform: uppercase;
    display: flex; flex-direction: column; align-items: center; gap: 6px;
    transition: opacity 0.4s ease;
  }
  .scroll-hint .chev { animation: bounce 1.6s infinite; font-size: 16px; }
  @keyframes bounce { 0%,100% { transform: translateY(0); } 50% { transform: translateY(6px); } }

  .app { position: relative; z-index: 1; max-width: 780px; margin: 0 auto; padding: 60px 20px 90px; }
  .brand { display: flex; align-items: center; gap: 14px; margin-bottom: 24px; }
  .brand .logo {
    width: 44px; height: 44px; border-radius: 12px;
    background: linear-gradient(135deg, #7c5cff, #5b8dff);
    display: flex; align-items: center; justify-content: center;
    font-size: 20px; font-weight: 700; color: #fff;
    box-shadow: 0 10px 22px -6px rgba(124,92,255,0.5);
  }
  .brand h1 { font-size: 21px; margin: 0; color: #14172a; }
  .brand p { margin: 2px 0 0; font-size: 13px; color: #767d94; }

  .card {
    background: rgba(255,255,255,0.75);
    border: 1px solid rgba(20,23,42,0.06);
    border-radius: 18px;
    padding: 26px 26px 22px;
    backdrop-filter: blur(14px);
    box-shadow: 0 24px 48px -24px rgba(20,23,42,0.18);
    margin-bottom: 20px;
  }

  label { font-size: 12.5px; color: #6b7188; display: block; margin: 14px 0 6px; letter-spacing: 0.2px; text-transform: uppercase; }
  label:first-of-type { margin-top: 0; }
  input, textarea {
    width: 100%; padding: 12px 14px; font-size: 14px; color: #1c2030;
    background: #fff;
    border: 1px solid rgba(20,23,42,0.12);
    border-radius: 10px; font-family: inherit;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  input:focus, textarea:focus {
    outline: none; border-color: #7c5cff;
    box-shadow: 0 0 0 3px rgba(124,92,255,0.15);
  }
  textarea { height: 92px; resize: vertical; }

  button#go {
    margin-top: 18px; width: 100%;
    padding: 14px 20px; font-size: 14.5px; font-weight: 600; letter-spacing: 0.3px;
    color: #fff; border: none; border-radius: 12px; cursor: pointer;
    background: linear-gradient(135deg, #7c5cff, #5b8dff);
    box-shadow: 0 10px 24px -6px rgba(124,92,255,0.45);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }
  button#go:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 14px 30px -6px rgba(124,92,255,0.55); }
  button#go:active:not(:disabled) { transform: translateY(1px) scale(0.99); }
  button#go:disabled { opacity: 0.55; cursor: not-allowed; }

  .status { font-weight: 600; margin: 16px 2px 0; font-size: 14px; color: #363c52; }

  #pipeline { display: none; }
  .vtrack { position: relative; padding-left: 4px; }
  .vline { position: absolute; left: 21px; top: 4px; bottom: 4px; width: 3px; background: rgba(20,23,42,0.08); border-radius: 2px; }
  .vline-fill { position: absolute; left: 21px; top: 4px; width: 3px; border-radius: 2px; transition: height 0.5s ease; height: 0px;
    background: linear-gradient(180deg, #7c5cff, #5b8dff); }
  .vnodes { position: relative; z-index: 2; }
  .vnode-row {
    display: flex; align-items: center; gap: 13px; padding: 8px 8px; cursor: pointer;
    border-radius: 10px; transition: background 0.2s ease;
  }
  .vnode-row:hover { background: rgba(124,92,255,0.06); }
  .vnode-row.selected { background: rgba(124,92,255,0.12); }
  .node {
    flex-shrink: 0; width: 40px; height: 40px; border-radius: 50%;
    background: #fff;
    border: 2.5px solid rgba(20,23,42,0.12);
    display: flex; align-items: center; justify-content: center; font-size: 16px;
    transition: border-color 0.3s, background 0.3s, box-shadow 0.3s;
    box-shadow: 0 3px 8px rgba(20,23,42,0.08);
  }
  .node.done {
    border-color: #7c5cff; background: linear-gradient(135deg, #7c5cff, #5b8dff);
    box-shadow: 0 6px 16px rgba(124,92,255,0.4);
  }
  .node.active { border-color: #f5a340; background: #fff2e0; animation: pulse 1.1s infinite; }
  .node.failed { border-color: #ef5a72; background: #ffeef1; }
  @keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(245,163,64,0.4); } 50% { box-shadow: 0 0 0 8px rgba(245,163,64,0); } }
  .marker { position: absolute; left: 11px; width: 22px; height: 22px; font-size: 17px; transition: top 0.6s ease; z-index: 3; }
  .vnode-label { font-size: 13.5px; color: #4a5069; text-transform: capitalize; }
  .vnode-row.done .vnode-label { color: #14172a; font-weight: 600; }
  .vnode-hint { font-size: 10px; color: #9aa1b8; margin-left: auto; letter-spacing: 0.3px; }

  #ops {
    display: none; background: #14172a; border: 1px solid rgba(255,255,255,0.06);
    padding: 12px 14px; border-radius: 12px; max-height: 220px; overflow-y: auto;
    font-size: 12.5px; font-family: "SF Mono", Consolas, monospace; color: #c6cade;
  }
  #ops .op { padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.06); }
  #ops .op:last-child { border-bottom: none; }
  #ops .stage { color: #8fb4ff; font-weight: 600; }
  #ops .st-completed { color: #6fe0a8; }
  #ops .st-failed { color: #ff8098; }
  #ops .st-skipped { color: #8991a8; }

  #codePanel { display: none; }
  #codePanel .filename {
    font-size: 12.5px; color: #4a5069; margin-bottom: 8px; font-family: monospace;
    display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
  }
  #codePanel .fileBtn {
    font-size: 11px; padding: 4px 10px; cursor: pointer; border-radius: 7px;
    border: 1px solid rgba(20,23,42,0.14); background: #fff; color: #363c52;
  }
  #codePanel .fileBtn:hover { background: rgba(124,92,255,0.08); border-color: #7c5cff; }
  #codeView {
    background: #14172a; color: #d8dbe8; padding: 16px 18px; border-radius: 12px;
    max-height: 360px; overflow: auto; font-size: 12.5px; line-height: 1.55;
    font-family: "SF Mono", Consolas, monospace; white-space: pre-wrap;
  }
  #codeView .cursor { display: inline-block; width: 7px; background: #8fb4ff; animation: blink 0.8s steps(1) infinite; }
  @keyframes blink { 50% { opacity: 0; } }

  #dl button {
    margin-top: 4px; padding: 11px 18px; font-size: 13.5px; font-weight: 600;
    color: #fff; border: none; border-radius: 10px; cursor: pointer;
    background: linear-gradient(135deg, #34c98f, #23a877);
    box-shadow: 0 8px 18px -4px rgba(35,168,119,0.4);
  }

  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-thumb { background: rgba(20,23,42,0.15); border-radius: 4px; }
</style>
</head>
<body>

<div class="hero">
  <div class="hero-pin">
    <canvas id="hero-canvas"></canvas>

    <div class="scene" id="scene-0">
      <p class="eyebrow">AURA</p>
      <h2>Describe what you want.</h2>
      <p>Type a plain-English request. That's the whole input.</p>
    </div>

    <div class="scene" id="scene-1">
      <p class="eyebrow">Agent pipeline</p>
      <h2>Watch it get built, agent by agent.</h2>
      <p>Requirements, architecture, code, tests, security, review -- each step runs, and you can watch every one of them happen.</p>
    </div>

    <div class="scene" id="scene-2">
      <p class="eyebrow">Ready</p>
      <h2>Ship something real.</h2>
      <p>Working code, tested and reviewed, ready to download.</p>
      <button class="cta" id="ctaBtn">Start building &darr;</button>
    </div>

    <div class="scroll-hint" id="scrollHint">
      <span>scroll</span>
      <span class="chev">&#8964;</span>
    </div>
  </div>
</div>

<div class="app" id="appSection">
  <div class="brand">
    <div class="logo">A</div>
    <div>
      <h1>AURA</h1>
      <p>Autonomous build pipeline</p>
    </div>
  </div>

  <div class="card">
    <label>Access code</label>
    <input id="code" type="password" placeholder="Access code">

    <label>Build request</label>
    <textarea id="req" placeholder='e.g. "A Flask API with a /hello endpoint that returns JSON"'></textarea>

    <button id="go">Start build</button>
    <div id="statusLine" class="status"></div>
  </div>

  <div class="card" id="pipelineCard" style="display:none">
    <div id="pipeline">
      <div class="vtrack">
        <div class="vline"></div>
        <div class="vline-fill" id="lineFill"></div>
        <div class="vnodes" id="nodes"></div>
        <div class="marker" id="marker">&#129302;</div>
      </div>
    </div>
  </div>

  <div class="card" id="codeCard" style="display:none">
    <div id="codePanel">
      <div class="filename" id="filename"></div>
      <div id="codeView"></div>
    </div>
  </div>

  <div class="card" id="opsCard" style="display:none">
    <div id="ops"></div>
  </div>

  <pre id="log" style="display:none"></pre>
  <div id="dl"></div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
(function initHero() {
  const canvas = document.getElementById('hero-canvas');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 100);
  camera.position.set(0, 0, 9);

  const key = new THREE.DirectionalLight(0xffffff, 1.1);
  key.position.set(4, 5, 6);
  scene.add(key);
  scene.add(new THREE.AmbientLight(0xffffff, 0.55));

  const coreGeom = new THREE.IcosahedronGeometry(2.1, 1);
  const coreMat = new THREE.MeshStandardMaterial({ color: 0x7c5cff, flatShading: true, roughness: 0.35, metalness: 0.15 });
  const core = new THREE.Mesh(coreGeom, coreMat);
  scene.add(core);

  const wireGeom = new THREE.IcosahedronGeometry(2.55, 1);
  const wireMat = new THREE.MeshBasicMaterial({ color: 0x5b8dff, wireframe: true, transparent: true, opacity: 0.35 });
  const wire = new THREE.Mesh(wireGeom, wireMat);
  scene.add(wire);

  const colorStops = [
    new THREE.Color(0x7c5cff),
    new THREE.Color(0x5b8dff),
    new THREE.Color(0x34c98f),
  ];

  const scenes = [0, 1, 2].map(i => document.getElementById('scene-' + i));
  const scrollHint = document.getElementById('scrollHint');
  const heroEl = document.querySelector('.hero');

  function getProgress() {
    const rect = heroEl.getBoundingClientRect();
    const scrollable = heroEl.offsetHeight - window.innerHeight;
    const scrolled = -rect.top;
    return Math.min(1, Math.max(0, scrolled / scrollable));
  }

  function updateScenes(p) {
    const bands = [[0, 0.36], [0.30, 0.70], [0.64, 1.0]];
    bands.forEach((b, i) => {
      scenes[i].classList.toggle('visible', p >= b[0] && p <= b[1]);
    });
    scrollHint.style.opacity = p < 0.04 ? '1' : '0';
  }

  function colorAt(p) {
    const scaled = p * (colorStops.length - 1);
    const i = Math.min(colorStops.length - 2, Math.floor(scaled));
    const local = scaled - i;
    return colorStops[i].clone().lerp(colorStops[i + 1], local);
  }

  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  let progress = 0;
  window.addEventListener('scroll', () => { progress = getProgress(); updateScenes(progress); }, { passive: true });
  updateScenes(0);

  function animate() {
    requestAnimationFrame(animate);
    core.rotation.y += 0.003 + progress * 0.01;
    core.rotation.x += 0.001;
    wire.rotation.y -= 0.002;
    wire.rotation.x += 0.0015;

    camera.position.z = 9 - progress * 2.5;
    const s = 1 + progress * 0.15;
    core.scale.setScalar(s);
    wire.scale.setScalar(s);

    const c = colorAt(progress);
    coreMat.color.copy(c);

    renderer.render(scene, camera);
  }
  animate();
})();

document.getElementById('ctaBtn').addEventListener('click', () => {
  document.getElementById('appSection').scrollIntoView({ behavior: 'smooth' });
  setTimeout(() => document.getElementById('code').focus(), 600);
});

const go = document.getElementById('go');
const statusLine = document.getElementById('statusLine');
const logEl = document.getElementById('log');
const dlEl = document.getElementById('dl');
const pipelineCard = document.getElementById('pipelineCard');
const nodesEl = document.getElementById('nodes');
const lineFillEl = document.getElementById('lineFill');
const markerEl = document.getElementById('marker');
const opsCard = document.getElementById('opsCard');
const opsEl = document.getElementById('ops');
const codeCard = document.getElementById('codeCard');
const codeViewEl = document.getElementById('codeView');
const filenameEl = document.getElementById('filename');

const STAGES = [
  ['requirements', '📋'], ['architect', '🏗️'], ['planner', '🗂️'], ['coder', '💻'],
  ['devops', '⚙️'], ['tester', '🧪'], ['debugger', '🐛'], ['security', '🔒'],
  ['dependency_scan', '📦'], ['runtime', '▶️'], ['reviewer', '👀'],
  ['critic', '🧐'], ['documentation', '📝'],
];
const STAGE_ICON = Object.fromEntries(STAGES);
const STATUS_EMOJI = { completed: '✅', failed: '❌', skipped: '⏭️' };

STAGES.forEach(([stage, icon]) => {
  const row = document.createElement('div');
  row.className = 'vnode-row';
  row.id = 'row-' + stage;
  row.onclick = () => selectStage(stage);
  const node = document.createElement('div');
  node.className = 'node';
  node.id = 'node-' + stage;
  node.textContent = icon;
  const label = document.createElement('span');
  label.className = 'vnode-label';
  label.textContent = stage.replace('_', ' ');
  const hint = document.createElement('span');
  hint.className = 'vnode-hint';
  hint.textContent = 'tap to view';
  row.appendChild(node);
  row.appendChild(label);
  row.appendChild(hint);
  nodesEl.appendChild(row);
});

let seenOps = 0;
let currentJobId = null;
let currentCode = null;
let stageData = {};
let selectedStage = null;
const fileQueue = [];
const queuedPaths = new Set();
let typing = false;

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function computeStageData(events) {
  const data = {};
  STAGES.forEach(([s]) => data[s] = { status: 'pending', detail: null, files: [] });
  let pending = [];
  events.forEach(ev => {
    if (ev.stage === 'file_written' && ev.status === 'completed' && ev.detail) {
      pending.push(ev.detail.replace(' (patch)', ''));
      return;
    }
    if (data[ev.stage] !== undefined) {
      data[ev.stage] = { status: ev.status, detail: ev.detail, files: pending.slice() };
      pending = [];
    }
  });
  return data;
}

async function selectStage(stage) {
  const info = stageData[stage];
  if (!info || info.status === 'pending') return;
  selectedStage = stage;
  document.querySelectorAll('.vnode-row').forEach(r => r.classList.remove('selected'));
  document.getElementById('row-' + stage).classList.add('selected');
  codeCard.style.display = 'block';

  if (info.files && info.files.length > 0) {
    await showFileInPanel(stage, info.files, 0);
  } else {
    const icon = STAGE_ICON[stage] || '🔎';
    const emoji = STATUS_EMOJI[info.status] || '';
    filenameEl.innerHTML = '<span>' + icon + ' ' + stage.replace('_', ' ') + ' ' + emoji + '</span>';
    codeViewEl.textContent = info.detail || '(no output recorded for this stage)';
  }
}

async function showFileInPanel(stage, files, idx) {
  const path = files[idx];
  const icon = STAGE_ICON[stage] || '💻';
  filenameEl.innerHTML = '';
  const header = document.createElement('span');
  header.textContent = icon + ' ' + stage.replace('_', ' ') + ' — ' + path;
  filenameEl.appendChild(header);
  files.forEach((f, i) => {
    if (files.length < 2) return;
    const btn = document.createElement('button');
    btn.className = 'fileBtn';
    btn.textContent = '📄 ' + f.split('/').pop();
    btn.onclick = (e) => { e.stopPropagation(); showFileInPanel(stage, files, i); };
    filenameEl.appendChild(btn);
  });
  codeViewEl.textContent = '⏳ loading...';
  try {
    const res = await fetch('/api/jobs/' + currentJobId + '/file?path=' + encodeURIComponent(path),
      { headers: { 'X-Access-Code': currentCode } });
    if (res.ok) {
      const data = await res.json();
      codeViewEl.textContent = data.content || '(empty file)';
    } else {
      codeViewEl.textContent = '⚠️ ' + (await res.json()).detail;
    }
  } catch (e) {
    codeViewEl.textContent = '⚠️ error loading file: ' + e;
  }
}

async function maybeStartTyping() {
  if (typing || fileQueue.length === 0 || !currentJobId || !currentCode) return;
  typing = true;
  const path = fileQueue.shift();
  codeCard.style.display = 'block';
  filenameEl.innerHTML = '<span>✍️ writing ' + path + ' ...</span>';
  codeViewEl.textContent = '';
  let content = '';
  try {
    const res = await fetch('/api/jobs/' + currentJobId + '/file?path=' + encodeURIComponent(path),
      { headers: { 'X-Access-Code': currentCode } });
    if (res.ok) content = (await res.json()).content || '';
  } catch (e) { /* file may not be readable yet -- just skip the animation for it */ }

  if (!content) { typing = false; maybeStartTyping(); return; }

  const totalTicks = 160;
  const chunkSize = Math.max(1, Math.ceil(content.length / totalTicks));
  let i = 0;
  const cursor = '<span class="cursor">&nbsp;</span>';
  const iv = setInterval(() => {
    i += chunkSize;
    const shown = content.slice(0, i);
    codeViewEl.innerHTML = escapeHtml(shown) + cursor;
    codeViewEl.scrollTop = codeViewEl.scrollHeight;
    if (i >= content.length) {
      clearInterval(iv);
      codeViewEl.innerHTML = escapeHtml(content);
      filenameEl.innerHTML = '<span>✅ ' + path + '</span>';
      typing = false;
      setTimeout(maybeStartTyping, 300);
    }
  }, 15);
}

function renderPipeline(events) {
  const stageIndex = {};
  STAGES.forEach(([s], i) => stageIndex[s] = i);
  let lastKnownIndex = -1;
  let anyFailed = false;

  events.forEach(ev => {
    const idx = stageIndex[ev.stage];
    if (idx === undefined) return;
    const node = document.getElementById('node-' + ev.stage);
    const row = document.getElementById('row-' + ev.stage);
    node.classList.remove('active', 'done', 'failed');
    row.classList.remove('done');
    if (ev.status === 'failed') { node.classList.add('failed'); anyFailed = true; }
    else { node.classList.add('done'); row.classList.add('done'); }
    if (idx > lastKnownIndex) lastKnownIndex = idx;
  });

  if (!anyFailed && lastKnownIndex >= 0 && lastKnownIndex < STAGES.length - 1) {
    const nextStage = STAGES[lastKnownIndex + 1][0];
    const nextNode = document.getElementById('node-' + nextStage);
    if (nextNode && !nextNode.classList.contains('done')) nextNode.classList.add('active');
  }

  if (lastKnownIndex >= 0) {
    const targetNode = document.getElementById('node-' + STAGES[lastKnownIndex][0]);
    const containerTop = nodesEl.getBoundingClientRect().top;
    const targetRect = targetNode.getBoundingClientRect();
    const centerY = targetRect.top - containerTop + targetRect.height / 2;
    lineFillEl.style.height = Math.max(0, centerY) + 'px';
    markerEl.style.top = Math.max(0, centerY - 11) + 'px';
  }

  stageData = computeStageData(events);

  for (let i = seenOps; i < events.length; i++) {
    const ev = events[i];
    const row = document.createElement('div');
    row.className = 'op';
    const emoji = STATUS_EMOJI[ev.status] || '•';
    row.innerHTML = emoji + ' <span class="stage">' + ev.stage + '</span> '
      + '<span class="st-' + ev.status + '">' + ev.status + '</span>'
      + (ev.detail ? ' — ' + ev.detail : '');
    opsEl.appendChild(row);

    if (ev.stage === 'file_written' && ev.status === 'completed' && ev.detail) {
      const path = ev.detail.replace(' (patch)', '');
      if (!queuedPaths.has(ev.detail)) {
        queuedPaths.add(ev.detail);
        fileQueue.push(path);
      }
    }
  }
  seenOps = events.length;
  opsEl.scrollTop = opsEl.scrollHeight;
  if (!selectedStage) maybeStartTyping();
}

function resetPipeline() {
  seenOps = 0;
  opsEl.innerHTML = '';
  lineFillEl.style.height = '0px';
  markerEl.style.top = '0px';
  fileQueue.length = 0;
  queuedPaths.clear();
  typing = false;
  stageData = {};
  selectedStage = null;
  filenameEl.textContent = '';
  codeViewEl.textContent = '';
  document.querySelectorAll('.node').forEach(n => n.classList.remove('active', 'done', 'failed'));
  document.querySelectorAll('.vnode-row').forEach(r => r.classList.remove('done', 'selected'));
}

go.onclick = async () => {
  const code = document.getElementById('code').value;
  const req = document.getElementById('req').value;
  if (!code || !req) { statusLine.textContent = 'Enter an access code and a request.'; return; }
  go.disabled = true;
  dlEl.innerHTML = '';
  logEl.textContent = '';
  pipelineCard.style.display = 'block';
  opsCard.style.display = 'block';
  codeCard.style.display = 'none';
  currentCode = code;
  resetPipeline();
  statusLine.textContent = '🚀 Submitting...';
  try {
    const res = await fetch('/api/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Access-Code': code },
      body: JSON.stringify({ request: req })
    });
    if (!res.ok) { statusLine.textContent = 'Error: ' + (await res.json()).detail; go.disabled = false; return; }
    const data = await res.json();
    poll(data.job_id, code);
  } catch (e) {
    statusLine.textContent = 'Request failed: ' + e;
    go.disabled = false;
  }
};

async function poll(jobId, code) {
  currentJobId = jobId;
  statusLine.textContent = 'Status: queued...';
  const iv = setInterval(async () => {
    const [statusRes, eventsRes] = await Promise.all([
      fetch('/api/jobs/' + jobId, { headers: { 'X-Access-Code': code } }),
      fetch('/api/jobs/' + jobId + '/events', { headers: { 'X-Access-Code': code } }),
    ]);
    const data = await statusRes.json();
    const eventsData = await eventsRes.json();
    statusLine.textContent = 'Status: ' + data.status;
    logEl.textContent = data.log_tail || '';
    renderPipeline(eventsData.events || []);

    if (data.status === 'done' || data.status === 'error') {
      clearInterval(iv);
      go.disabled = false;
      if (data.status === 'done') {
        statusLine.textContent = '🎉 Status: done';
        const btn = document.createElement('button');
        btn.textContent = '⬇️ Download result (.zip)';
        btn.onclick = async () => {
          const r = await fetch('/api/jobs/' + jobId + '/download', { headers: { 'X-Access-Code': code } });
          const blob = await r.blob();
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = 'aura-build-' + jobId + '.zip';
          a.click();
        };
        dlEl.innerHTML = '';
        dlEl.appendChild(btn);
      } else {
        statusLine.textContent += ' -- ' + (data.error || 'unknown error');
      }
    }
  }, 1500);
}
</script>
</body>
</html>
"""
