"""ReproCam API + UI.

    python -m backend.api            # http://localhost:8000  (also serves the store on :5173)

POST /runs                      upload a video (multipart "video") -> {id, events}
GET  /runs/{id}/events          Server-Sent Events, live, until the run's result is written
GET  /runs/{id}                 run summary: result, steps, test, verdict, evidence, ticket
GET  /runs/{id}/video           the uploaded recording (the UI opens finished runs at /?run=<id>)
POST /runs/{id}/fixcheck        re-run the run's test on the fixed build (?fixed=1); no model calls
GET  /samples                   cached sample runs
POST /samples/{id}/replay       -> {events}: where to stream the replay from
GET  /samples/{id}/events       replays the cached events with their original timing ($0)
GET  /samples/{id}              same summary as a run;  POST /samples/{id}/fixcheck likewise
GET  /{runs|samples}/{id}/files/{path}   artifacts (keyframes, evidence, screenshots, video)
"""
import asyncio
import json
import os
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend import budget
from backend.agent import ROOT, run_pipeline, store_running
from backend.runner import failure_summary, run_test

RUNS, SAMPLES, WEB = ROOT / "runs", ROOT / "samples", ROOT / "web"
APP_URL = os.getenv("APP_URL", "http://localhost:5173").rstrip("/")
ID = re.compile(r"^[a-z0-9_-]{1,40}$")
_live = threading.Lock()  # one live run at a time: each drives a browser and several model calls


@asynccontextmanager
async def lifespan(app: FastAPI):
    with store_running(APP_URL):  # the app under test, unless something already serves it
        yield


app = FastAPI(title="ReproCam", lifespan=lifespan)
# The practice store, on the same domain: what testers record and what judges can click through.
app.mount("/store", StaticFiles(directory=ROOT / "store", html=True), name="store")
PERSIST = None  # set by the Modal app to commit its Volume after writes


def _persist():
    if PERSIST:
        try:
            PERSIST()
        except Exception:  # noqa: BLE001  (a failed commit must not fail the request)
            pass


def client_ip(request: Request) -> str:
    """Visitor IP for the per-IP cap. Behind Modal's proxy the client is the right-most
    X-Forwarded-For entry (added by the proxy, so a visitor can't spoof it by sending the header)."""
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[-1].strip() if forwarded else request.client.host


def _dir(kind: str, rid: str) -> Path:
    if not ID.match(rid):
        raise HTTPException(404, "not found")
    d = (RUNS if kind == "runs" else SAMPLES) / rid
    if not d.is_dir():
        raise HTTPException(404, "not found")
    return d


def _json(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def summary(d: Path, kind: str) -> dict:
    """Everything the UI shows for a finished (or running) run, with artifact URLs."""
    base = f"/{kind}/{d.name}/files/"
    result, steps = _json(d / "result.json"), _json(d / "steps.json")
    attempts = []
    for a in sorted(d.glob("attempt_*")):
        buggy = _json(a / "buggy" / "result.json")
        fixed = _json(a / "known_good" / "result.json") or _json(a / "fixed" / "result.json")  # older runs: fixed/
        attempts.append({
            "name": a.name,
            "test_code": (a / "test_repro.py").read_text() if (a / "test_repro.py").exists() else None,
            "verdict": _json(a / "verdict.json"),
            "buggy": buggy and {"outcome": buggy["outcome"], "summary": failure_summary(buggy.get("message"))},
            "fixed": fixed and {"outcome": fixed["outcome"], "summary": failure_summary(fixed.get("message"))},
        })
    seg = _json(d / "segment.json")
    if seg:
        seg = {k: seg.get(k) for k in ("method", "sam_mode", "concept", "candidates", "picked", "pick_reason", "box")} | {
            "frame_url": base + seg["frame"]["path"], "tried": [
                {k: t.get(k) for k in ("concept", "mode", "boxes", "on_bug_frame", "frames_processed")}
                for t in seg.get("tried", [])]}
    frames = _json(d / "frames.json")
    transcript = _json(d / "transcript.json")
    return {
        "id": d.name, "kind": kind, "result": result, "steps": steps,
        "transcript": transcript and transcript.get("transcript", "").strip(),
        "keyframes": [{"n": f["n"], "t": f["t"], "url": base + f["path"]} for f in (frames or {}).get("frames", [])
                      if (d / f["path"]).exists()],
        "video_url": base + "video.mp4" if (d / "video.mp4").exists() else
                     (f"/runs/{d.name}/video" if kind == "runs" and _upload(d.name) else None),
        "attempts": attempts, "segment": seg,
        "evidence_url": base + "evidence.png" if (d / "evidence.png").exists() else None,
        "ticket_md": (d / "ticket.md").read_text() if (d / "ticket.md").exists() else None,
        "files_base": base,
    }


def _upload(rid: str) -> Path | None:
    return next((RUNS / "_uploads").glob(f"{rid}.*"), None) if ID.match(rid) else None


def _sse(obj, event: str | None = None) -> str:
    return (f"event: {event}\n" if event else "") + f"data: {json.dumps(obj)}\n\n"


# ---------- live runs ----------

@app.get("/api/config")
def get_config():
    """What the page needs to label live runs: where Muse Spark Open is served from."""
    from backend.llm import PROVIDERS, image_limit
    understand = (os.getenv("UNDERSTAND_PROVIDER") or os.getenv("LLM_PROVIDER", "meta")).lower()
    provider = os.getenv("LLM_PROVIDER", "meta").lower()
    return {"llm_provider": provider, "llm_model": os.getenv(PROVIDERS[provider][2]), "max_images": image_limit(),
            "understand_provider": understand, "understand_model": os.getenv(PROVIDERS[understand][2]),
            "understand_max_images": image_limit(understand)}


@app.get("/api/budget")
def get_budget(request: Request):
    return budget.status(client_ip(request))


@app.post("/runs")
async def create_run(request: Request, video: UploadFile):
    ip = client_ip(request)
    if _live.locked():
        raise HTTPException(429, "Another live run is in progress. Try again in a minute, or replay a sample.")
    rid = "u" + uuid.uuid4().hex[:10]
    ext = Path(video.filename or "").suffix.lower() if Path(video.filename or "").suffix.lower() in \
        (".mp4", ".mov", ".webm", ".m4v") else ".mp4"
    upload = RUNS / "_uploads" / f"{rid}{ext}"
    upload.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with upload.open("wb") as f:
        while chunk := await video.read(1 << 20):
            size += len(chunk)
            if size > budget.MAX_BYTES:
                f.close()
                upload.unlink(missing_ok=True)
                raise HTTPException(413, f"Upload is over {budget.MAX_BYTES // 2**20} MB.")
            f.write(chunk)
    try:
        budget.check_video(upload)
        left = budget.charge(ip, owner=budget.is_owner(request.query_params.get("owner")))
    except budget.BudgetError as e:
        upload.unlink(missing_ok=True)
        raise HTTPException(e.status, str(e)) from None
    _persist()

    run_dir = RUNS / rid
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text("")

    def work():
        with _live:
            try:
                run_pipeline(str(upload), run_dir=run_dir)
            except Exception:  # noqa: BLE001  (already written to result.json by the agent)
                pass
            _persist()

    threading.Thread(target=work, daemon=True).start()
    return {"id": rid, "events": f"/runs/{rid}/events", **left}


@app.get("/runs/{rid}/video")
def run_video(rid: str):
    """The uploaded recording of a live run (for /?run=<id> links)."""
    f = _upload(rid)
    if not f:
        raise HTTPException(404, "not found")
    return FileResponse(f)


@app.get("/runs/{rid}/events")
async def run_events(rid: str):
    d = _dir("runs", rid)

    async def stream():
        sent, deadline = 0, time.time() + 600
        while time.time() < deadline:
            lines = (d / "events.jsonl").read_text().splitlines() if (d / "events.jsonl").exists() else []
            for line in lines[sent:]:
                yield f"data: {line}\n\n"
            sent = len(lines)
            if (d / "result.json").exists() and sent == len((d / "events.jsonl").read_text().splitlines()):
                yield _sse(_json(d / "result.json"), "done")
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


# ---------- samples ----------

@app.get("/samples")
def list_samples():
    return [_json(p) for p in sorted(SAMPLES.glob("*/sample.json"))]


@app.post("/samples/{sid}/replay")
def replay(sid: str):
    _dir("samples", sid)
    return {"id": sid, "events": f"/samples/{sid}/events"}


@app.get("/samples/{sid}/events")
async def sample_events(sid: str, speed: float = 1.0, after: int = 0, offset: float = 0.0):
    """Replay from event `after` on, as if `offset` seconds of the original run had passed
    (lets the UI change speed mid-replay by reconnecting)."""
    d = _dir("samples", sid)
    events = [json.loads(line) for line in (d / "events.jsonl").read_text().splitlines() if line.strip()]
    speed = min(max(speed, 0.5), 20.0)

    async def stream():
        started = time.time()
        for e in events[max(0, after):]:
            wait = (e["t"] - offset) / speed - (time.time() - started)
            if wait > 0:
                await asyncio.sleep(wait)
            yield _sse({**e, "replay": True})
        yield _sse(_json(d / "result.json"), "done")

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


# ---------- shared ----------

@app.get("/{kind}/{rid}")
def get_summary(kind: str, rid: str):
    if kind not in ("runs", "samples"):
        raise HTTPException(404, "not found")
    return summary(_dir(kind, rid), kind)


@app.get("/{kind}/{rid}/files/{path:path}")
def get_file(kind: str, rid: str, path: str):
    if kind not in ("runs", "samples"):
        raise HTTPException(404, "not found")
    d = _dir(kind, rid).resolve()
    f = (d / path).resolve()
    if d not in f.parents or not f.is_file() or f.suffix.lower() not in (".jpg", ".png", ".mp4", ".json", ".md", ".py"):
        raise HTTPException(404, "not found")
    return FileResponse(f)


@app.post("/{kind}/{rid}/fixcheck")
def fixcheck(kind: str, rid: str):
    """Run the reproducing test against the fixed build. Free: Playwright only, no model calls."""
    if kind not in ("runs", "samples"):
        raise HTTPException(404, "not found")
    d = _dir(kind, rid)
    result = _json(d / "result.json") or {}
    test = d / result.get("test", "")
    if not result.get("test") or not test.is_file():
        raise HTTPException(409, "This run has no reproducing test yet.")
    out = run_test(test.read_text(), RUNS / "_fixcheck" / f"{kind}-{rid}-{int(time.time())}", APP_URL, fixed=True)
    return {"outcome": out["outcome"], "summary": failure_summary(out.get("message")), "seconds": out["seconds"]}


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
