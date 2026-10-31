"""ReproCam on Modal: one public URL for the app (/) and the practice store (/store/).

    modal secret create reprocam-keys --from-dotenv .env     # keys live in a Modal Secret, never in the image
    modal deploy deploy/modal_app.py

The web container runs the agent but never runs generated tests: those go to a Modal Sandbox
(backend/modal_sandbox.py) with no network beyond the store served inside it and no secrets.
Live runs, uploads and the budget counters live on a Volume. One container, so the event
stream and the run it reports on share a filesystem.
"""
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
REMOTE = "/root/reprocam"

# Never ship secrets, local runs, recordings (samples/<id>/video.mp4 is the web copy) or dev files.
IGNORE = [".env", ".env.*", "**/.env", "**/.env.*", ".venv", ".git", "runs", "**/__pycache__", ".pytest_cache", "samples/*.mov",
          "docs", "tests", "deploy", "data/llm_calls.jsonl", "data/judge_log.jsonl", "**/.DS_Store"]

web_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install_from_requirements(str(ROOT / "requirements.txt"))
    .env({
        "REPRO_SANDBOX": "modal",              # generated tests run in a Modal Sandbox
        "APP_URL": "http://localhost:5173",    # the store as the sandbox serves it to the test
        "KNOWN_GOOD_URL": "fixed",             # the practice store has a fixed build: verify every run
        "PYTHONPATH": REMOTE,
    })
    .add_local_dir(ROOT, REMOTE, ignore=IGNORE)
)

app = modal.App("reprocam")
runs = modal.Volume.from_name("reprocam-runs", create_if_missing=True)


@app.function(image=web_image, secrets=[modal.Secret.from_name("reprocam-keys")],
              volumes={f"{REMOTE}/runs": runs}, max_containers=1, scaledown_window=600, timeout=900)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    import os
    import sys

    os.chdir(REMOTE)
    sys.path.insert(0, REMOTE)
    from backend import api

    api.PERSIST = runs.commit  # budget counters and finished runs survive container restarts
    return api.app
