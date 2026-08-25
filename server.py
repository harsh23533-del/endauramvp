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
<title>AURA MVP</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; color: #1a1a1a; }
  textarea, input { width: 100%; box-sizing: border-box; padding: 10px; font-size: 14px; border: 1px solid #ccc; border-radius: 6px; }
  textarea { height: 90px; margin-bottom: 10px; }
  button { padding: 10px 18px; font-size: 14px; border: none; border-radius: 6px; background: #111; color: #fff; cursor: pointer; margin-top: 10px; }
  button:disabled { background: #999; cursor: not-allowed; }
  pre { background: #0d1117; color: #c9d1d9; padding: 14px; border-radius: 6px; max-height: 240px; overflow: auto; font-size: 12px; white-space: pre-wrap; }
  .status { font-weight: 600; margin-top: 14px; }
  label { font-size: 13px; color: #555; display: block; margin-top: 12px; margin-bottom: 4px; }

  #pipeline { display: none; margin-top: 24px; }
  .track { position: relative; height: 54px; margin: 0 6px 6px; }
  .track .line { position: absolute; top: 17px; left: 0; right: 0; height: 4px; background: #e5e5e5; border-radius: 2px; }
  .track .line-fill { position: absolute; top: 17px; left: 0; height: 4px; background: #111; border-radius: 2px; transition: width 0.5s ease; width: 0%; }
  .nodes { display: flex; justify-content: space-between; position: relative; }
  .node { width: 38px; height: 38px; border-radius: 50%; background: #fff; border: 3px solid #e5e5e5; display: flex; align-items: center; justify-content: center; font-size: 15px; z-index: 2; transition: border-color 0.3s, background 0.3s; }
  .node.done { border-color: #111; background: #111; color: #fff; }
  .node.active { border-color: #d97706; background: #fff7ed; animation: pulse 1s infinite; }
  .node.failed { border-color: #dc2626; background: #fef2f2; }
  @keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(217,119,6,0.35); } 50% { box-shadow: 0 0 0 6px rgba(217,119,6,0); } }
  .marker { position: absolute; top: 4px; width: 20px; height: 20px; font-size: 16px; transform: translateX(-50%); transition: left 0.6s ease; z-index: 3; }
  .labels { display: flex; justify-content: space-between; margin-top: 4px; }
  .labels span { font-size: 10px; color: #777; width: 46px; text-align: center; transform: translateX(-4px); }

  #ops { display: none; background: #0d1117; color: #c9d1d9; padding: 12px 14px; border-radius: 6px; max-height: 220px; overflow-y: auto; font-size: 12.5px; margin-top: 14px; }
  #ops .op { padding: 3px 0; border-bottom: 1px solid #1f2937; }
  #ops .op:last-child { border-bottom: none; }
  #ops .stage { color: #58a6ff; font-weight: 600; }
  #ops .st-completed { color: #3fb950; }
  #ops .st-failed { color: #f85149; }
  #ops .st-skipped { color: #999; }
</style>
</head>
<body>
  <h2>AURA MVP</h2>
  <p>Describe what you want built. Builds run one at a time, so yours may queue behind others.</p>

  <label>Access code</label>
  <input id="code" type="password" placeholder="Access code">

  <label>Build request</label>
  <textarea id="req" placeholder='e.g. "Make me a Flask API with a /hello endpoint"'></textarea>

  <button id="go">Start build</button>

  <div id="statusLine" class="status"></div>

  <div id="pipeline">
    <div class="track">
      <div class="line"></div>
      <div class="line-fill" id="lineFill"></div>
      <div class="nodes" id="nodes"></div>
      <div class="marker" id="marker">🤖</div>
    </div>
    <div class="labels" id="labels"></div>
  </div>

  <div id="ops"></div>

  <pre id="log" style="display:none"></pre>
  <div id="dl"></div>

<script>
const go = document.getElementById('go');
const statusLine = document.getElementById('statusLine');
const logEl = document.getElementById('log');
const dlEl = document.getElementById('dl');
const pipelineEl = document.getElementById('pipeline');
const nodesEl = document.getElementById('nodes');
const labelsEl = document.getElementById('labels');
const lineFillEl = document.getElementById('lineFill');
const markerEl = document.getElementById('marker');
const opsEl = document.getElementById('ops');

// Fixed pipeline order (matches core/orchestrator.py's log_event() call
// sequence). Stages not in this list (e.g. "database", "issue_agent") only
// run conditionally, so they still show up in the operations feed below but
// don't get a dedicated node -- keeps the pipeline diagram a stable shape.
const STAGES = [
  ['requirements', '📋'], ['architect', '🏗️'], ['planner', '🗂️'], ['coder', '💻'],
  ['devops', '⚙️'], ['tester', '🧪'], ['debugger', '🐛'], ['security', '🔒'],
  ['dependency_scan', '📦'], ['runtime', '▶️'], ['reviewer', '👀'],
  ['critic', '🧐'], ['documentation', '📝'],
];

STAGES.forEach(([stage, icon]) => {
  const node = document.createElement('div');
  node.className = 'node';
  node.id = 'node-' + stage;
  node.textContent = icon;
  nodesEl.appendChild(node);
  const label = document.createElement('span');
  label.textContent = stage;
  labelsEl.appendChild(label);
});

let seenOps = 0;

function renderPipeline(events) {
  const stageIndex = {};
  STAGES.forEach(([s], i) => stageIndex[s] = i);
  let lastKnownIndex = -1;
  let anyFailed = false;

  events.forEach(ev => {
    const idx = stageIndex[ev.stage];
    if (idx === undefined) return;
    const node = document.getElementById('node-' + ev.stage);
    node.classList.remove('active', 'done', 'failed');
    if (ev.status === 'failed') { node.classList.add('failed'); anyFailed = true; }
    else { node.classList.add('done'); }
    if (idx > lastKnownIndex) lastKnownIndex = idx;
  });

  // Mark the node just past the last completed one as "active" (in progress),
  // unless the run already failed there.
  if (!anyFailed && lastKnownIndex >= 0 && lastKnownIndex < STAGES.length - 1) {
    const nextStage = STAGES[lastKnownIndex + 1][0];
    const nextNode = document.getElementById('node-' + nextStage);
    if (nextNode && !nextNode.classList.contains('done')) nextNode.classList.add('active');
  }

  const pct = STAGES.length > 1 ? (lastKnownIndex / (STAGES.length - 1)) * 100 : 0;
  lineFillEl.style.width = Math.max(0, pct) + '%';
  const nodeWidth = nodesEl.offsetWidth || 1;
  const markerPct = STAGES.length > 1 ? (Math.max(0, lastKnownIndex) / (STAGES.length - 1)) : 0;
  markerEl.style.left = (markerPct * nodeWidth) + 'px';

  // Operations feed: append only new events since last render.
  for (let i = seenOps; i < events.length; i++) {
    const ev = events[i];
    const row = document.createElement('div');
    row.className = 'op';
    row.innerHTML = '<span class="stage">' + ev.stage + '</span> '
      + '<span class="st-' + ev.status + '">' + ev.status + '</span>'
      + (ev.detail ? ' — ' + ev.detail : '');
    opsEl.appendChild(row);
  }
  seenOps = events.length;
  opsEl.scrollTop = opsEl.scrollHeight;
}

function resetPipeline() {
  seenOps = 0;
  opsEl.innerHTML = '';
  lineFillEl.style.width = '0%';
  markerEl.style.left = '0px';
  document.querySelectorAll('.node').forEach(n => n.classList.remove('active', 'done', 'failed'));
}

go.onclick = async () => {
  const code = document.getElementById('code').value;
  const req = document.getElementById('req').value;
  if (!code || !req) { statusLine.textContent = 'Enter an access code and a request.'; return; }
  go.disabled = true;
  dlEl.innerHTML = '';
  logEl.style.display = 'block';
  logEl.textContent = '';
  pipelineEl.style.display = 'block';
  opsEl.style.display = 'block';
  resetPipeline();
  statusLine.textContent = 'Submitting...';
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
    logEl.scrollTop = logEl.scrollHeight;
    renderPipeline(eventsData.events || []);

    if (data.status === 'done' || data.status === 'error') {
      clearInterval(iv);
      go.disabled = false;
      if (data.status === 'done') {
        const btn = document.createElement('button');
        btn.textContent = 'Download result (.zip)';
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
