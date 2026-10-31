"""Run one generated test with pytest and report how it ended. Standard library only, so this
same file runs locally (from backend/runner.py) and inside the Modal Sandbox (as a script).

The test process gets a minimal environment: no API keys or other secrets, only what Python
and Playwright need plus APP_URL / REPRO_FIXED / REPRO_ACTION_TIMEOUT_MS.

Sandbox use:  python sandbox_exec.py  < job.json   ->  one line "@@RESULT@@{...}" on stdout
The job also names a directory of static files (the practice store) to serve on localhost,
so the test reaches the store without any network access.
"""
import base64
import json
import os
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MARK = "@@RESULT@@"
SAFE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH")


def execute(code: str, plugin: str, workdir: str | Path, app_url: str, fixed: bool,
            action_timeout_ms: int, timeout_s: int, query: str = "") -> dict:
    """Write test_repro.py + the result plugin into workdir and run pytest there."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "test_repro.py").write_text(code)
    (workdir / "conftest.py").write_text(plugin)
    (workdir / "pytest.ini").write_text("[pytest]\n")  # keep any surrounding pytest.ini out of it
    (workdir / "result.json").unlink(missing_ok=True)

    env = {k: os.environ[k] for k in SAFE_ENV if k in os.environ}
    env.update(APP_URL=app_url, REPRO_FIXED="1" if fixed else "0", REPRO_ACTION_TIMEOUT_MS=str(action_timeout_ms),
               REPRO_QUERY=query)
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "-p", "no:warnings", "--tb=short",
             "--screenshot", "on", "--output", "artifacts", "test_repro.py"],
            cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout_s)
        output = proc.stdout + proc.stderr
        result = json.loads((workdir / "result.json").read_text()) if (workdir / "result.json").exists() \
            else {"outcome": "error", "phase": "session", "exc_type": None, "message": output[-3000:]}
    except subprocess.TimeoutExpired as e:
        output = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        result = {"outcome": "error", "phase": "timeout", "exc_type": "subprocess.TimeoutExpired",
                  "message": f"test did not finish within {timeout_s}s"}
    shots = sorted((workdir / "artifacts").rglob("*.png"))
    return {**result, "fixed": fixed, "seconds": round(time.time() - started, 1), "output": output[-3000:],
            "screenshot": str(shots[-1]) if shots else None}


def _serve(directory: str, port: int) -> None:
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Quiet, directory=directory))
    threading.Thread(target=server.serve_forever, daemon=True).start()


if __name__ == "__main__":
    job = json.load(sys.stdin)
    _serve(job["store_dir"], job["store_port"])
    res = execute(job["code"], job["plugin"], job["workdir"], f"http://localhost:{job['store_port']}",
                  job["fixed"], job["action_timeout_ms"], job["timeout_s"], job.get("query", ""))
    if res["screenshot"]:
        res["screenshot_png"] = base64.b64encode(Path(res["screenshot"]).read_bytes()).decode()
    print(MARK + json.dumps(res), flush=True)
