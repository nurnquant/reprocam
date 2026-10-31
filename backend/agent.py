"""The verify loop: video -> steps -> test -> run -> judge -> retry (<= 3) -> fix check.

    python -m backend.agent samples/bug1.mov              # full pipeline
    python -m backend.agent samples/bug1.mov --from-steps # reuse runs/bug1/steps.json

Events go to runs/<name>/events.jsonl (contract in BUILD_PLAN). Every verdict is logged to
data/judge_log.jsonl together with the oracle: the same test re-run on the fixed build.
The oracle never steers the loop; only the judge does (in real use there is no fixed build).
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from backend import media, testgen
from backend.judge import judge
from backend.llm import effort_for
from backend.runner import run_test
from backend.transcribe import MODEL as TRANSCRIBE_MODEL
from backend.transcribe import transcribe
from backend.understand import understand

ROOT = Path(__file__).resolve().parent.parent
JUDGE_LOG = ROOT / "data" / "judge_log.jsonl"
MAX_ATTEMPTS = 3
# Sample videos whose bug is known, so judge log rows carry a bug id (None for real uploads).
SAMPLE_BUGS = {"bug1": "neg_total", "bug2": "qty_stepper", "bug3": "zip_hang"}

sys.path.insert(0, str(ROOT / "scripts"))
from serve_store import store_running  # noqa: E402


class Run:
    def __init__(self, run_dir: Path):
        self.dir = run_dir
        self.started = time.time()
        self.events = run_dir / "events.jsonl"
        self.events.write_text("")
        self.calls: list[dict] = []

    def emit(self, stage, status, detail, meta=None, attempt=None, artifact=None):
        if meta and status != "start":
            self.calls.append(meta)
        event = {"t": round(time.time() - self.started, 2), "stage": stage, "status": status,
                 "model": meta and meta.get("model"), "provider": meta and meta.get("provider"),
                 "effort": meta and meta.get("effort"), "attempt": attempt, "detail": detail,
                 "artifact": artifact and os.path.relpath(artifact, self.dir)}
        with self.events.open("a") as f:
            f.write(json.dumps(event) + "\n")
        tag = f"[{event['t']:6.1f}s] {stage:<10} {status:<5}"
        badge = f" ({meta['provider']} · effort {meta['effort']})" if meta and meta.get("effort") else ""
        print(f"{tag} {detail}{badge}")

    def cost(self) -> float | None:
        known = [c["cost_usd"] for c in self.calls if c.get("cost_usd") is not None]
        return round(sum(known), 4) if known else None


def failure_text(result: dict) -> str:
    return f"{result['outcome']} ({result.get('exc_type')}): {result.get('message', '')}"


def log_verdict(run_id, bug_id, attempt, claim, code, result, verdict, oracle, meta):
    JUDGE_LOG.parent.mkdir(exist_ok=True)
    row = {"ts": round(time.time(), 1), "run_id": run_id, "bug_id": bug_id, "attempt": attempt,
           "bug_claim": claim, "test_code": code,
           "test_hash": hashlib.sha256(code.encode()).hexdigest()[:12],
           "pytest_output": (failure_text(result) + "\n" + result.get("output", ""))[:3000],
           "verdict": verdict["verdict"], "decided_by": verdict["decided_by"], "reason": verdict["reason"],
           "oracle": oracle, "judge_provider": meta and meta["provider"], "judge_effort": meta and meta["effort"]}
    with JUDGE_LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")


def run_pipeline(video: str, bug_id: str | None = None, from_steps: bool = False) -> dict:
    video = Path(video)
    run_dir = ROOT / "runs" / video.stem
    run_dir.mkdir(parents=True, exist_ok=True)
    for old in run_dir.glob("attempt_*"):
        shutil.rmtree(old)
    run = Run(run_dir)
    run_id = f"{video.stem}-{int(run.started)}"
    bug_id = bug_id or SAMPLE_BUGS.get(video.stem)
    app_url = os.getenv("APP_URL", "http://localhost:5173").rstrip("/")

    if from_steps:
        run.emit("understand", "ok", "reusing cached steps.json", artifact=run_dir / "steps.json")
    else:
        run.emit("frames", "start", f"extracting audio and keyframes from {video.name}")
        prepared = media.prepare(video, run_dir)
        run.emit("frames", "ok", f"{len(prepared['frames'])} keyframes", artifact=run_dir / "frames.json")
        if prepared["audio"]:
            run.emit("transcribe", "start", "transcribing narration")
            t = transcribe(run_dir / "audio.wav")
            (run_dir / "transcript.json").write_text(json.dumps(t, indent=2))
            run.emit("transcribe", "ok", f'"{t["transcript"].strip()[:80]}"',
                     {"stage": "transcribe", "model": TRANSCRIBE_MODEL, "provider": "meta", "effort": None, "cost_usd": None},
                     artifact=run_dir / "transcript.json")
        run.emit("understand", "start", "reading keyframes + narration")
        u = understand(run_dir)
        run.emit("understand", "ok", f"{len(u['steps']['steps'])} steps; claim: {u['steps']['bug_claim']['summary']}",
                 u["meta"], artifact=run_dir / "steps.json")
    steps = json.loads((run_dir / "steps.json").read_text())
    claim = steps["bug_claim"]

    previous, final, verdict = [], None, None
    with store_running(app_url):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            adir = run_dir / f"attempt_{attempt}"
            run.emit("testgen", "start", f"writing test (effort {effort_for('testgen')})", attempt=attempt)
            code, notes, gen_meta = testgen.generate(steps, previous)
            adir.mkdir()
            (adir / "test_repro.py").write_text(code)
            run.emit("testgen", "ok", notes, gen_meta, attempt, adir / "test_repro.py")

            problem = testgen.lint(code)
            if problem:
                result = {"outcome": "error", "phase": "lint", "exc_type": "Lint", "message": problem, "output": ""}
                run.emit("run", "fail", f"not run: {problem}", attempt=attempt)
            else:
                run.emit("run", "start", "running on buggy build (?fixed=0)", attempt=attempt)
                result = run_test(code, adir / "buggy", app_url, fixed=False)
                run.emit("run", "ok" if result["outcome"] == "pass" else "fail",
                         f"{result['outcome']}: {(result.get('message') or '').splitlines()[0][:120] if result.get('message') else 'passed'}",
                         attempt=attempt, artifact=result.get("screenshot"))

            verdict, judge_meta = judge(claim, code, result)
            (adir / "verdict.json").write_text(json.dumps(verdict, indent=2))
            run.emit("judge", "ok" if verdict["verdict"] == "REPRODUCED" else "fail",
                     f"{verdict['verdict']} ({verdict['decided_by']}): {verdict['reason']}",
                     judge_meta, attempt, adir / "verdict.json")

            # Oracle: same test on the fixed build. Logged for training data and used as the fix
            # check; never fed back into the loop.
            fixed = run_test(code, adir / "fixed", app_url, fixed=True) if not problem else result
            oracle = {"buggy": result["outcome"], "fixed": fixed["outcome"]}
            log_verdict(run_id, bug_id, attempt, claim, code, result, verdict, oracle, judge_meta)

            if verdict["verdict"] == "REPRODUCED":
                ok = fixed["outcome"] == "pass"
                run.emit("fixcheck", "ok" if ok else "fail",
                         "passes on fixed build (?fixed=1)" if ok else f"fails on fixed build: {failure_text(fixed)[:150]}",
                         attempt=attempt, artifact=fixed.get("screenshot"))
                final = {"verdict": "REPRODUCED", "attempt": attempt, "fixcheck": fixed["outcome"],
                         "test": str(adir / "test_repro.py"), "failure": failure_text(result)}
                break
            previous.append({"test_code": code, "outcome": result["outcome"],
                             "failure": failure_text(result), "feedback": verdict["feedback_for_generator"]})
            if attempt < MAX_ATTEMPTS:
                run.emit("judge", "retry", "feeding judge feedback back to the test writer", attempt=attempt)

    final = final or {"verdict": verdict["verdict"], "attempt": MAX_ATTEMPTS, "fixcheck": None}
    final.update(run_id=run_id, bug_id=bug_id, seconds=round(time.time() - run.started, 1), cost_usd=run.cost(),
                 model_calls=[{k: c.get(k) for k in ("stage", "provider", "effort", "prompt_tokens",
                                                     "completion_tokens", "cost_usd")} for c in run.calls])
    (run_dir / "result.json").write_text(json.dumps(final, indent=2))
    return final


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--bug-id")
    ap.add_argument("--from-steps", action="store_true", help="reuse runs/<name>/steps.json")
    args = ap.parse_args()
    out = run_pipeline(args.video, args.bug_id, args.from_steps)
    print(f"\n{out['verdict']} after {out['attempt']} attempt(s) · fix check: {out['fixcheck']} · "
          f"{out['seconds']}s · model cost ${out['cost_usd']}")
