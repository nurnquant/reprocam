"""Run one generated test inside a Modal Sandbox (used when REPRO_SANDBOX=modal).

Isolation:
- block_network=True: no network at all. The practice store is copied into the sandbox image and
  served on localhost inside it, so the test reaches the store and nothing else.
- secrets=[]: no API keys. The sandbox image is built from public packages + the store files +
  backend/sandbox_exec.py only.
- timeout=120 s hard limit (pytest itself stops at 60 s), cpu=1, memory=2 GiB.
"""
import json
from pathlib import Path

import modal

from backend.sandbox_exec import MARK

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "reprocam-tests"
STORE_PORT = 5173

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("pytest>=8", "pytest-playwright>=0.5", "playwright>=1.45")
    .run_commands("playwright install --with-deps chromium")
    .add_local_dir(ROOT / "store", "/store")
    .add_local_file(ROOT / "backend" / "sandbox_exec.py", "/opt/sandbox_exec.py")
)


def run_in_sandbox(code: str, plugin: str, fixed: bool, action_timeout_ms: int, timeout_s: int,
                   query: str = "") -> dict:
    app = modal.App.lookup(APP_NAME, create_if_missing=True)
    sb = modal.Sandbox.create(app=app, image=image, secrets=[], block_network=True,
                              timeout=120, cpu=1.0, memory=2048, workdir="/work")
    try:
        job = {"code": code, "plugin": plugin, "workdir": "/work/test", "fixed": fixed, "store_dir": "/store",
               "store_port": STORE_PORT, "action_timeout_ms": action_timeout_ms, "timeout_s": timeout_s,
               "query": query}
        proc = sb.exec("python", "/opt/sandbox_exec.py")
        proc.stdin.write(json.dumps(job))
        proc.stdin.write_eof()
        proc.stdin.drain()
        out = proc.stdout.read()
        err = proc.stderr.read()
        proc.wait()
    finally:
        sb.terminate()
    line = next((ln for ln in out.splitlines() if ln.startswith(MARK)), None)
    if line is None:
        return {"outcome": "error", "phase": "sandbox", "exc_type": "SandboxError", "fixed": fixed, "seconds": None,
                "message": f"sandbox returned no result: {(err or out)[-1500:]}", "output": (out + err)[-3000:]}
    return json.loads(line[len(MARK):])
