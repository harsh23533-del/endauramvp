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
            archive_path = _archive_workspace(job_id)
            with jobs_lock:
                job["status"] = "done"
                job["report"] = _slim_report(report)
                job["archive"] = archive_path
        except Exception as e:  # noqa: BLE001 -- surface any failure to the caller
            with jobs_lock:
                job["status"] = "error"
                job["error"] = str(e)
        finally:
            with jobs_lock:
                job["log"] = log_buffer.getvalue()[-20000:]  # cap stored log size
            work_queue.task_done()


threading.Thread(target=_worker, daemon=True).start()


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
  pre { background: #0d1117; color: #c9d1d9; padding: 14px; border-radius: 6px; max-height: 360px; overflow: auto; font-size: 12px; white-space: pre-wrap; }
  .status { font-weight: 600; margin-top: 14px; }
  label { font-size: 13px; color: #555; display: block; margin-top: 12px; margin-bottom: 4px; }
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
  <pre id="log" style="display:none"></pre>
  <div id="dl"></div>

<script>
const go = document.getElementById('go');
const statusLine = document.getElementById('statusLine');
const logEl = document.getElementById('log');
const dlEl = document.getElementById('dl');

go.onclick = async () => {
  const code = document.getElementById('code').value;
  const req = document.getElementById('req').value;
  if (!code || !req) { statusLine.textContent = 'Enter an access code and a request.'; return; }
  go.disabled = true;
  dlEl.innerHTML = '';
  logEl.style.display = 'block';
  logEl.textContent = '';
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
    const res = await fetch('/api/jobs/' + jobId, { headers: { 'X-Access-Code': code } });
    const data = await res.json();
    statusLine.textContent = 'Status: ' + data.status;
    logEl.textContent = data.log_tail || '';
    logEl.scrollTop = logEl.scrollHeight;
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
  }, 2000);
}
</script>
</body>
</html>
"""
